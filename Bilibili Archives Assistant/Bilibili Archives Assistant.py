import aiohttp
import asyncio
import traceback
from datetime import datetime
from Hyper import Configurator

Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())

TRIGGHT_KEYWORD = "查投稿"
HELP_MESSAGE = f"{Configurator.cm.get_cfg().others['reminder']}查投稿 (B站用户mid) [关键词] [页码] —> 查询B站UP主的投稿视频列表"

def parse_parameters(params_str):
    params = params_str.split()
    if not params:
        return None, None, "1"
    
    mid = params[0]
    
    if len(params) == 1:
        return mid, None, "1"
    
    if len(params) == 2:
        if params[1].isdigit():
            return mid, None, params[1]
        else:
            return mid, params[1], "1"
    
    if params[-1].isdigit():
        pn = params[-1]
        keywords = " ".join(params[1:-1])
    else:
        pn = "1"
        keywords = " ".join(params[1:])
    
    return mid, keywords, pn

async def on_message(event, actions, Manager, Segments):
    waiting_msg_id = None
    
    try:
        user_message = str(event.message)
        reminder = Configurator.cm.get_cfg().others["reminder"]
        prefix = f"{reminder}{TRIGGHT_KEYWORD}"
        
        if not user_message.startswith(prefix):
            return
        
        params_str = user_message[len(prefix):].strip()
        
        if not params_str:
            help_text = f"""📺 B站投稿查询插件
————————————————————
格式：{prefix} [mid] [关键词] [页码]

示例：
{prefix} 401742377 → 查询第1页
{prefix} 401742377 2 → 查询第2页（无关键词）
{prefix} 401742377 原神 → 搜索"原神"相关视频
{prefix} 401742377 原神 2 → 搜索"原神"相关视频，查看第2页"""
                
            await actions.send(
                group_id=event.group_id,
                message=Manager.Message(Segments.Reply(event.message_id), Segments.Text(help_text))
            )
            return True
            
        mid, keywords, pn = parse_parameters(params_str)
        
        if not mid:
            await actions.send(
                group_id=event.group_id,
                message=Manager.Message(Segments.Reply(event.message_id), 
                Segments.Text("❌ 错误：请提供B站用户mid"))
            )
            return True
        
        if not mid.isdigit():
            await actions.send(
                group_id=event.group_id,
                message=Manager.Message(Segments.Reply(event.message_id), 
                Segments.Text("❌ 错误：mid必须是数字"))
            )
            return True
        
        if not pn.isdigit() or int(pn) <= 0:
            await actions.send(
                group_id=event.group_id,
                message=Manager.Message(Segments.Reply(event.message_id), 
                Segments.Text("❌ 错误：页码必须是正整数"))
            )
            return True
        
        waiting_msg = await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Reply(event.message_id), 
            Segments.Text(f"🔍 正在查询用户 {mid} 的投稿，请稍候..."))
        )
        waiting_msg_id = waiting_msg.data.message_id if waiting_msg.data else None
        
        api_url = "https://uapis.cn/api/v1/social/bilibili/archives"
        
        query_params = {
            "mid": mid,
            "orderby": "pubdate",
            "ps": "5",
            "pn": pn
        }
        
        if keywords:
            query_params["keywords"] = keywords
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=query_params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if waiting_msg_id:
                        try:
                            await actions.del_message(waiting_msg_id)
                        except:
                            pass
                    
                    if "videos" in data and data["videos"]:
                        videos = data["videos"]
                        total = data.get("total", 0)
                        page = data.get("page", 1)
                        
                        total_pages = (total + 4) // 5
                        
                        reply_parts = []
                        
                        keywords_text = f" 关键词：{keywords}" if keywords else ""
                        title = f"📺 B站用户 {mid} 投稿查询结果{keywords_text}\n"
                        title += f"第{page}页/共{total_pages}页 | 每页5条 | 按最新发布排序\n"
                        title += "————————————————————\n"
                        reply_parts.append(Segments.Text(title))
                        
                        for i, video in enumerate(videos, 1):
                            title_text = video.get("title", "未知标题")
                            bvid = video.get("bvid", "")
                            play_count = video.get("play_count", 0)
                            duration = video.get("duration", 0)
                            publish_time = video.get("publish_time", 0)
                            cover_url = video.get("cover", "")
                            
                            if bvid.startswith("BV"):
                                short_link = f"https://b23.tv/{bvid}"
                            else:
                                short_link = f"https://www.bilibili.com/video/{bvid}"
                            
                            if play_count >= 10000:
                                play_text = f"{play_count/10000:.1f}万"
                            else:
                                play_text = f"{play_count}"
                            
                            minutes = duration // 60
                            seconds = duration % 60
                            duration_text = f"{minutes}:{seconds:02d}"
                            
                            if publish_time:
                                pub_date = datetime.fromtimestamp(publish_time).strftime("%Y-%m-%d")
                            else:
                                pub_date = "未知时间"
                            
                            if len(title_text) > 40:
                                title_text = title_text[:37] + "..."
                            
                            # 构建视频信息（包含封面图片）
                            video_info = f"{i}. {title_text}\n"
                            video_info += f"   📊 {play_text}播放 ⏱️{duration_text} 📅{pub_date}\n"
                            video_info += f"   🔗 {short_link}"
                            
                            # 如果有封面URL，添加封面图片
                            if cover_url and cover_url.startswith("http"):
                                try:
                                    # 添加封面图片
                                    reply_parts.append(Segments.Image(cover_url))
                                except:
                                    pass  # 如果图片发送失败，继续发送文本信息
                            
                            reply_parts.append(Segments.Text(video_info))
                        
                        footer = "————————————————————\n"
                        footer += f"总计投稿：{total} 个 | 本页显示：{len(videos)} 个\n"
                        
                        if total_pages > 1:
                            footer += f"\n📄 分页导航：\n"
                            if int(page) > 1:
                                if keywords:
                                    footer += f"上一页：{prefix} {mid} {keywords} {int(page)-1}\n"
                                else:
                                    footer += f"上一页：{prefix} {mid} {int(page)-1}\n"
                            if int(page) < total_pages:
                                if keywords:
                                    footer += f"下一页：{prefix} {mid} {keywords} {int(page)+1}"
                                else:
                                    footer += f"下一页：{prefix} {mid} {int(page)+1}"
                        
                        reply_parts.append(Segments.Text(footer))
                        
                        # 分批发送消息，避免一次性消息太长
                        try:
                            # 先发送前半部分（标题和视频信息）
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(*reply_parts[:len(reply_parts)-1])
                            )
                            
                            # 再发送页脚信息（分页导航）
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(reply_parts[-1])
                            )
                        except:
                            # 如果分批发送失败，尝试一次性发送
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(*reply_parts)
                            )
                    else:
                        error_msg = f"❌ 未找到用户 {mid} 的投稿视频"
                        if keywords:
                            error_msg += f"，或关键词 '{keywords}' 无匹配结果"
                        if int(pn) > 1:
                            error_msg += f"\n页码 {pn} 超出范围，请尝试第1页"
                        
                        await actions.send(
                            group_id=event.group_id,
                            message=Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
                        )
                elif response.status == 400:
                    if waiting_msg_id:
                        try:
                            await actions.del_message(waiting_msg_id)
                        except:
                            pass
                            
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(Segments.Reply(event.message_id), 
                        Segments.Text("❌ API请求错误：缺少必要的mid参数"))
                    )
                elif response.status == 404:
                    if waiting_msg_id:
                        try:
                            await actions.del_message(waiting_msg_id)
                        except:
                            pass
                            
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(Segments.Reply(event.message_id), 
                        Segments.Text(f"❌ 未找到用户ID为 {mid} 的B站用户"))
                    )
                elif response.status == 500:
                    if waiting_msg_id:
                        try:
                            await actions.del_message(waiting_msg_id)
                        except:
                            pass
                            
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(Segments.Reply(event.message_id), 
                        Segments.Text("❌ B站API服务器错误，请稍后再试"))
                    )
                else:
                    if waiting_msg_id:
                        try:
                            await actions.del_message(waiting_msg_id)
                        except:
                            pass
                            
                    await actions.send(
                        group_id=event.group_id,
                        message=Manager.Message(Segments.Reply(event.message_id), 
                        Segments.Text(f"❌ API请求失败，状态码：{response.status}"))
                    )
    
    except asyncio.TimeoutError:
        if waiting_msg_id:
            try:
                await actions.del_message(waiting_msg_id)
            except:
                pass
                
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Reply(event.message_id), 
            Segments.Text("⏱️ 查询超时，请稍后重试"))
        )
    except aiohttp.ClientError as e:
        if waiting_msg_id:
            try:
                await actions.del_message(waiting_msg_id)
            except:
                pass
                
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Reply(event.message_id), 
            Segments.Text(f"🌐 网络错误：{str(e)}"))
        )
    except Exception as e:
        if waiting_msg_id:
            try:
                await actions.del_message(waiting_msg_id)
            except:
                pass
        
        print(f"B站投稿查询插件错误：{traceback.format_exc()}")
        
        error_msg = "❌ 插件执行出错\n"
        error_msg += f"错误信息：{str(e)[:50]}...\n"
        error_msg += "————————————————————\n"
        error_msg += f"💡 使用帮助：发送 '{prefix}' 查看详细说明"
        
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Reply(event.message_id), Segments.Text(error_msg))
        )
    
    return True

# 插件加载时打印信息
print(f"[B站投稿查询插件] 已成功加载")