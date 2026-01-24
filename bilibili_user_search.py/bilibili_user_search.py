import aiohttp
import json
import re
import time
import asyncio
from Hyper import Configurator

# 加载配置文件
Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())

# 获取配置信息
reminder = Configurator.cm.get_cfg().others["reminder"]
bot_name = Configurator.cm.get_cfg().others["bot_name"]

# 插件触发关键词
TRIGGHT_KEYWORD = "查B站用户"

# 帮助信息
HELP_MESSAGE = f"{reminder}查B站用户 [UID] —> 查询B站用户的公开信息\n例如：{reminder}查B站用户 401742377"

# 冷却时间字典
cooldowns = {}

async def on_message(event, actions, Manager, Segments):
    # 获取消息内容
    msg = str(event.message)
    user_id = event.user_id
    
    # 检查冷却时间
    current_time = time.time()
    if user_id in cooldowns and current_time - cooldowns[user_id] < 5:
        time_remaining = 5 - (current_time - cooldowns[user_id])
        await actions.send(
            group_id=event.group_id, 
            message=Manager.Message(
                Segments.Text(f"冷却时间5秒，请等待 {time_remaining:.1f} 秒后再试")
            )
        )
        return True
    
    # 检查是否包含触发关键词
    if not msg.startswith(f"{reminder}{TRIGGHT_KEYWORD}"):
        return
    
    # 提取UID
    uid_str = msg[len(f"{reminder}{TRIGGHT_KEYWORD}"):].strip()
    
    if not uid_str:
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(
                Segments.Reply(event.message_id),
                Segments.Text(f"请提供B站用户的UID哦~\n例如：{reminder}查B站用户 401742377")
            )
        )
        return True
    
    # 提取数字UID
    uid_match = re.search(r'(\d+)', uid_str)
    if not uid_match:
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(
                Segments.Reply(event.message_id),
                Segments.Text(f"UID必须是纯数字哦~\n你输入的：{uid_str}")
            )
        )
        return True
    
    uid = uid_match.group(1)
    
    # 发送等待消息
    selfID = await actions.send(
        group_id=event.group_id,
        message=Manager.Message(
            Segments.Text(f"{bot_name}正在努力查询B站用户信息中... ╰(°▽°)╯")
        )
    )
    
    try:
        api_url = "https://uapis.cn/api/v1/social/bilibili/userinfo"
        params = {"uid": uid}
        
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    user_info = data
                    face_url = user_info.get('face', '')
                    
                    text_parts = []
                    text_parts.append("📺 B站用户信息查询成功！ ✧٩(ˊωˋ*)و✧")
                    text_parts.append("══════════════════════════════")
                    
                    text_parts.append(f"🔢 UID：{user_info.get('mid', uid)}")
                    text_parts.append(f"📛 昵称：{user_info.get('name', '未知用户')}")
                    
                    sex = user_info.get('sex', '保密')
                    sex_emoji = "🕵️"
                    if sex == "男":
                        sex_emoji = "👨"
                    elif sex == "女":
                        sex_emoji = "👩"
                    text_parts.append(f"⚧️ 性别：{sex} {sex_emoji}")
                    
                    level = user_info.get('level', 0)
                    level_stars = "⭐" * min(level, 6)
                    text_parts.append(f"⭐ 等级：Lv{level} {level_stars}")
                    
                    sign = user_info.get('sign', '这个用户很懒，还没有签名~')
                    if sign and len(sign) > 0:
                        text_parts.append(f"📝 签名：{sign}")
                    
                    follower = user_info.get('follower', 0)
                    following = user_info.get('following', 0)
                    text_parts.append(f"❤️ 粉丝数：{follower:,}")
                    text_parts.append(f"👀 关注数：{following:,}")
                    
                    if follower > 0 and following > 0:
                        ratio = follower / following
                        if ratio > 100000:
                            ratio_text = f"{ratio:,.0f}:1"
                        elif ratio > 1000:
                            ratio_text = f"{ratio:,.1f}:1"
                        else:
                            ratio_text = f"{ratio:.1f}:1"
                            
                        if ratio > 100000:
                            text_parts.append(f"📊 粉丝关注比：{ratio_text} (现象级大V！)")
                        elif ratio > 10000:
                            text_parts.append(f"📊 粉丝关注比：{ratio_text} (顶级大V！)")
                        elif ratio > 1000:
                            text_parts.append(f"📊 粉丝关注比：{ratio_text} (超级大V！)")
                        elif ratio > 100:
                            text_parts.append(f"📊 粉丝关注比：{ratio_text} (大V认证！)")
                        elif ratio > 10:
                            text_parts.append(f"📊 粉丝关注比：{ratio_text} (人气不错~)")
                        else:
                            text_parts.append(f"📊 粉丝关注比：{ratio_text}")
                    
                    archive_count = user_info.get('archive_count', 0)
                    article_count = user_info.get('article_count', 0)
                    text_parts.append(f"🎬 视频数：{archive_count:,}")
                    text_parts.append(f"📰 专栏数：{article_count:,}")
                    
                    vip_type = user_info.get('vip_type', 0)
                    vip_status = user_info.get('vip_status', 0)
                    if vip_type > 0 and vip_status == 1:
                        if vip_type == 2:
                            text_parts.append(f"💎 大会员：尊贵的大会员用户")
                        else:
                            text_parts.append(f"💎 大会员：VIP用户")
                    
                    if follower > 10000000:
                        text_parts.append("══════════════════════════════")
                        text_parts.append(f"🏆 哇！{user_info.get('name', '该用户')} 有超过千万粉丝，是现象级大V！")
                    elif follower > 1000000:
                        text_parts.append("══════════════════════════════")
                        text_parts.append(f"🎉 哇！{user_info.get('name', '该用户')} 有超过百万粉丝，是超级大V呢！")
                    elif follower > 100000:
                        text_parts.append("══════════════════════════════")
                        text_parts.append(f"✨ {user_info.get('name', '该用户')} 有超过十万粉丝，人气很高哦！")
                    
                    text_message = "\n".join(text_parts)
                    
                    await actions.del_message(selfID.data.message_id)
                    
                    message_segments = []
                    message_segments.append(Segments.Reply(event.message_id))
                    
                    if face_url:
                        message_segments.append(Segments.Image(face_url))
                    
                    message_segments.append(Segments.Text(text_message))
                    
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(*message_segments)
                    )
                    
                else:
                    await actions.del_message(selfID.data.message_id)
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(
                            Segments.Reply(event.message_id),
                            Segments.Text(f"❌ API请求失败，状态码：{response.status}")
                        )
                    )
                    
        cooldowns[user_id] = current_time
        
    except aiohttp.ClientError:
        await actions.del_message(selfID.data.message_id)
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(
                Segments.Reply(event.message_id),
                Segments.Text("❌ 网络请求错误")
            )
        )
    except asyncio.TimeoutError:
        await actions.del_message(selfID.data.message_id)
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(
                Segments.Reply(event.message_id),
                Segments.Text("⏰ 请求超时，请稍后再试")
            )
        )
    except Exception:
        await actions.del_message(selfID.data.message_id)
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(
                Segments.Reply(event.message_id),
                Segments.Text("❌ 发生未知错误")
            )
        )
    
    return True

print("[B站用户查询插件] 已成功加载")