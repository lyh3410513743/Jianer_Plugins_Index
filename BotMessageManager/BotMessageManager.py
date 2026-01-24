import os
import re
import time
import asyncio
import threading
from Hyper import Configurator

Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())

config = Configurator.cm.get_cfg()
reminder = config.others["reminder"]
bot_name = config.others["bot_name"]

TRIGGHT_KEYWORD = "撤回"
HELP_MESSAGE = f"{reminder}撤回 —> 撤回您触发{bot_name}发送的消息"

MESSAGE_RETENTION_TIME = 60

def get_help_message():
    return HELP_MESSAGE

def load_user_list(filename):
    try:
        if not os.path.exists(filename):
            with open(filename, 'w', encoding='utf-8') as f:
                pass
            return []
        
        with open(filename, 'r', encoding='utf-8') as f:
            users = [line.strip() for line in f if line.strip()]
            return list(set(users))
    except Exception as e:
        return []

def get_admins():
    try:
        config = Configurator.cm.get_cfg()
        ROOT_User = []
        if hasattr(config, 'owner'):
            ROOT_User = [str(uid) for uid in getattr(config, 'owner', [])]
        elif hasattr(config, 'others') and 'ROOT_User' in config.others:
            ROOT_User = config.others.get('ROOT_User', [])
        
        Super_User = load_user_list("Super_User.ini")
        Manage_User = load_user_list("Manage_User.ini")
        
        ADMINS = []
        ADMINS.extend(Super_User)
        ADMINS.extend(Manage_User)
        ADMINS.extend(ROOT_User)
        
        return list(set(ADMINS))
    except Exception as e:
        return []

def get_replied_message_id(message_data):
    if hasattr(message_data, 'message') and isinstance(message_data.message, list):
        for segment in message_data.message:
            if isinstance(segment, dict) and segment.get('type') == 'reply':
                return segment.get('data', {}).get('id')
    
    if hasattr(message_data, 'raw_message'):
        raw_msg = str(message_data.raw_message)
        pattern = r'\[CQ:reply,id=(\d+)\]'
        match = re.search(pattern, raw_msg)
        if match:
            return match.group(1)
    
    return None

def is_message_too_old(message_data, max_minutes=2):
    try:
        if hasattr(message_data, 'time'):
            message_time = int(message_data.time)
        elif isinstance(message_data, dict) and 'time' in message_data:
            message_time = int(message_data['time'])
        else:
            return False
        
        current_time = int(time.time())
        time_diff = current_time - message_time
        minutes_diff = time_diff / 60
        return minutes_diff > max_minutes
    except Exception:
        return False

def extract_qq_from_message_content(message_content, robot_qq):
    extracted_qqs = set()
    
    if isinstance(message_content, str):
        qq_pattern = r'\b([1-9]\d{4,10})\b'
        matches = re.findall(qq_pattern, message_content)
        extracted_qqs.update(matches)
        
        cq_pattern = r'\[CQ:at,qq=(\d+)\]'
        cq_matches = re.findall(cq_pattern, message_content)
        extracted_qqs.update(cq_matches)
    
    elif isinstance(message_content, list):
        for segment in message_content:
            if isinstance(segment, dict):
                if segment.get('type') == 'text':
                    text = segment.get('data', {}).get('text', '')
                    qq_pattern = r'\b([1-9]\d{4,10})\b'
                    matches = re.findall(qq_pattern, text)
                    extracted_qqs.update(matches)
                elif segment.get('type') == 'at':
                    qq = segment.get('data', {}).get('qq', '')
                    if qq:
                        extracted_qqs.add(str(qq))
    
    filtered_qqs = []
    for qq in extracted_qqs:
        qq_str = str(qq)
        if qq_str and qq_str != robot_qq and qq_str != '0' and len(qq_str) >= 5:
            filtered_qqs.append(qq_str)
    
    return filtered_qqs

async def is_robot_reply_to_user(message_data, current_user_id, robot_qq, actions):
    replied_msg_id = get_replied_message_id(message_data)
    
    if replied_msg_id:
        try:
            replied_msg = await actions.get_msg(replied_msg_id)
            if replied_msg and hasattr(replied_msg, 'data'):
                replied_data = replied_msg.data
                if hasattr(replied_data, 'user_id'):
                    replied_user_id = str(replied_data.user_id)
                elif isinstance(replied_data, dict) and 'user_id' in replied_data:
                    replied_user_id = str(replied_data['user_id'])
                else:
                    replied_user_id = None
                
                if replied_user_id:
                    return replied_user_id == str(current_user_id)
        except:
            pass
    
    try:
        message_content = None
        
        if hasattr(message_data, 'message'):
            message_content = message_data.message
        elif hasattr(message_data, 'raw_message'):
            message_content = message_data.raw_message
        elif isinstance(message_data, dict):
            message_content = message_data.get('message') or message_data.get('raw_message')
        
        if message_content:
            extracted_qqs = extract_qq_from_message_content(message_content, robot_qq)
            
            if str(current_user_id) in extracted_qqs:
                return True
    except Exception:
        pass
    
    return False

async def schedule_message_deletion(sent_msg, actions):
    try:
        if sent_msg and hasattr(sent_msg, 'data') and hasattr(sent_msg.data, 'message_id'):
            message_id = sent_msg.data.message_id
            
            def delete_message_sync():
                time.sleep(MESSAGE_RETENTION_TIME)
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    async def delete():
                        try:
                            await actions.del_message(message_id)
                        except Exception:
                            pass
                    
                    loop.run_until_complete(delete())
                    loop.close()
                except Exception:
                    pass
            
            thread = threading.Thread(target=delete_message_sync, daemon=True)
            thread.start()
                    
    except Exception:
        pass

async def send_message_with_auto_delete(actions, group_id, message):
    try:
        sent_msg = await actions.send(group_id=group_id, message=message)
        
        if sent_msg:
            asyncio.create_task(schedule_message_deletion(sent_msg, actions))
            return sent_msg
        else:
            return None
            
    except Exception:
        return None

async def on_message(event, actions, Manager, Segments):
    try:
        if not hasattr(event, 'group_id') or not event.group_id:
            return None
        
        user_id = str(event.user_id)
        group_id = str(event.group_id)
        robot_qq = str(event.self_id) if hasattr(event, 'self_id') else ""
        
        ADMINS = get_admins()
        is_admin = user_id in ADMINS
        
        user_message = str(event.message)
        
        if not user_message.startswith(f"{reminder}{TRIGGHT_KEYWORD}"):
            return None
        
        if not event.message or not isinstance(event.message[0], Segments.Reply):
            help_msg = f"回复{bot_name}的消息并发送 {reminder}撤回 来撤回该消息。"
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Reply(event.message_id), Segments.Text(help_msg))
            )
            return True
        
        target_message_id = event.message[0].id
        
        try:
            target_msg = await actions.get_msg(target_message_id)
            
            if not target_msg or not hasattr(target_msg, 'data'):
                error_msg = f"{bot_name}无法获取被引用的消息。"
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
                )
                return True
            
            message_data = target_msg.data
            
            sender_id = None
            if hasattr(message_data, 'user_id'):
                sender_id = str(message_data.user_id)
            elif isinstance(message_data, dict) and 'user_id' in message_data:
                sender_id = str(message_data['user_id'])
            
            if sender_id != robot_qq:
                error_msg = f"只能撤回{bot_name}发送的消息。"
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
                )
                return True
            
            if not is_admin:
                is_trigger = await is_robot_reply_to_user(message_data, user_id, robot_qq, actions)
                
                if not is_trigger:
                    error_msg = f"只能撤回自己触发的{bot_name}消息。"
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
                    )
                    return True
                
                if is_message_too_old(message_data, 2):
                    error_msg = f"消息已超过2分钟，无法撤回{bot_name}的消息。"
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
                    )
                    return True
            
            try:
                await actions.del_message(target_message_id)
                
                success_msg = f"✅ {bot_name}已撤回消息"
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Reply(event.message_id), Segments.Text(success_msg))
                )
                
            except Exception as e:
                error_str = str(e).lower()
                
                if "message already recalled" in error_str or "已被撤回" in error_str:
                    response_msg = f"{bot_name}消息已被撤回"
                elif "permission" in error_str or "权限" in error_str:
                    response_msg = f"{bot_name}权限不足，无法撤回"
                elif "timeout" in error_str or "time" in error_str:
                    response_msg = f"{bot_name}消息已过期，无法撤回"
                else:
                    response_msg = f"{bot_name}撤回失败，请稍后重试"
                
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Reply(event.message_id), Segments.Text(response_msg))
                )
            
            return True
            
        except Exception:
            try:
                await actions.del_message(target_message_id)
                success_msg = f"✅ {bot_name}已撤回消息"
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Reply(event.message_id), Segments.Text(success_msg))
                )
                return True
            except:
                error_msg = f"{bot_name}撤回失败"
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
                )
                return True
        
    except Exception:
        return True

print(f"[撤回插件] ✅ 已加载")