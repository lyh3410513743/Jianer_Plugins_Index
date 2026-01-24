import aiohttp
import asyncio
from Hyper import Configurator
from datetime import datetime
import html
import math

Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())

reminder = Configurator.cm.get_cfg().others["reminder"]
bot_name = Configurator.cm.get_cfg().others["bot_name"]

TRIGGHT_KEYWORD = "b站评论"
HELP_MESSAGE = f"{reminder}{TRIGGHT_KEYWORD} [视频ID] [页码] —> 查询B站视频评论"

BILIBILI_API_URL = "https://uapis.cn/api/v1/social/bilibili/replies"

async def on_message(event, actions, Manager, Segments, order, bot_name, reminder):
    if not order.startswith(TRIGGHT_KEYWORD):
        return
    
    command = order[len(TRIGGHT_KEYWORD):].strip()
    
    if not command:
        help_text = f'''📺B站评论查询
————————————————————
格式：{reminder}{TRIGGHT_KEYWORD} [视频ID] (页码)

示例：
{reminder}{TRIGGHT_KEYWORD} 115852649174965
{reminder}{TRIGGHT_KEYWORD} 115852649174965 2
视频ID可以通过Bilibili Archives Assistant插件获取'''
        
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text(help_text))
        )
        return True
    
    params = command.split()
    
    if len(params) < 1:
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text("❌ 请输入视频ID"))
        )
        return True
    
    video_id = params[0]
    page_num = "1"
    
    if len(params) > 1:
        page_num = params[1]
    
    try:
        pn_int = int(page_num)
        if pn_int < 1:
            await actions.send(
                group_id=event.group_id,
                message=Manager.Message(Segments.Text("❌ 页码必须大于0"))
            )
            return True
    
    except ValueError:
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text("❌ 页码格式错误"))
        )
        return True
    
    loading_msg = await actions.send(
        group_id=event.group_id,
        message=Manager.Message(Segments.Text(f"🔍 查询中..."))
    )
    
    try:
        api_params = {
            "oid": video_id,
            "sort": "1",
            "ps": "5",
            "pn": page_num
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(BILIBILI_API_URL, params=api_params, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    try:
                        await actions.del_message(loading_msg.data.message_id)
                    except:
                        pass
                    
                    formatted_comments = format_comments(data, video_id, page_num)
                    
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(Segments.Text(formatted_comments))
                    )
                else:
                    try:
                        await actions.del_message(loading_msg.data.message_id)
                    except:
                        pass
                    
                    error_text = f"❌ 查询失败：{response.status}"
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(Segments.Text(error_text))
                    )
    
    except aiohttp.ClientError:
        try:
            await actions.del_message(loading_msg.data.message_id)
        except:
            pass
        
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text("❌ 网络请求失败"))
        )
    
    except asyncio.TimeoutError:
        try:
            await actions.del_message(loading_msg.data.message_id)
        except:
            pass
        
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text("❌ 请求超时"))
        )
    
    except Exception:
        try:
            await actions.del_message(loading_msg.data.message_id)
        except:
            pass
        
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text("❌ 发生错误"))
        )
    
    return True

def format_comments(data, video_id, page_num):
    page_info = data.get("page", {})
    total_comments = page_info.get("count", 0)
    current_page = int(page_num)
    total_pages = math.ceil(total_comments / 5) if total_comments > 0 else 1
    
    result = f"📺 B站评论\n"
    result += "=" * 30 + "\n"
    result += f"视频ID: {video_id}\n"
    result += f"页码: {current_page}/{total_pages}\n"
    result += f"评论总数: {total_comments}\n"
    result += "=" * 30 + "\n\n"
    
    if "replies" in data and data["replies"]:
        for i, comment in enumerate(data["replies"], 1):
            result += format_single_comment(comment, i, current_page)
            result += "-" * 20 + "\n"
    else:
        result += "📭 暂无评论\n"
    
    if current_page < total_pages:
        next_page = current_page + 1
        result += f"\n➡️ 使用 {reminder}{TRIGGHT_KEYWORD} {video_id} {next_page} 查看下一页"
    else:
        result += f"\n✅ 已显示所有评论"
    
    return result

def format_single_comment(comment, index, current_page):
    try:
        member = comment.get("member", {})
        uname = member.get("uname", "未知用户")
        level_info = member.get("level_info", {})
        level = level_info.get("current_level", 0)
        
        content = comment.get("content", {})
        message = content.get("message", "")
        message = html.unescape(message)
        message = message.replace("\n", " ")
        if len(message) > 80:
            message = message[:80] + "..."
        
        like = comment.get("like", 0)
        
        ctime = comment.get("ctime", 0)
        if ctime:
            try:
                time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
            except:
                time_str = "未知时间"
        else:
            time_str = "未知时间"
        
        reply_control = comment.get("reply_control", {})
        location = reply_control.get("location", "")
        ip_location = ""
        if location and "IP属地：" in location:
            ip_location = location.replace("IP属地：", "").strip()
        
        formatted = f"{index}. [{uname}] Lv.{level}\n"
        formatted += f"   👍 {like}赞 | 📅 {time_str}"
        if ip_location:
            formatted += f" | IP属地 {ip_location}"
        formatted += "\n"
        
        if message == "发表图片":
            formatted += f"   📷 [图片评论]\n"
        else:
            formatted += f"   💬 {message}\n"
        
        return formatted
        
    except Exception:
        return f"{index}. 评论解析失败\n"

print("[B站评论插件] 已加载")