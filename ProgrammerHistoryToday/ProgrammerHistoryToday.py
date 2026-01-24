print("[程序员历史上的今天插件] 已成功加载")

import aiohttp
import json
import asyncio
from datetime import datetime
from Hyper import Configurator

# 加载配置
Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())
config = Configurator.cm.get_cfg()

TRIGGHT_KEYWORD = "程序员历史上的今天"
HELP_MESSAGE = f"{config.others['reminder']}程序员历史上的今天 —> 查看程序员历史上的今天发生了什么重要事件 📜"

async def on_message(event, actions, Manager, Segments, reminder, bot_name, bot_name_en, ONE_SLOGAN):
    """
    处理"程序员历史上的今天"命令
    """
    # 构建消息头
    header = f"{bot_name} {bot_name_en} - {ONE_SLOGAN}\n————————————————————"
    
    try:
        # 发送正在获取的提示
        loading_msg = await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text(f"{header}\n正在查询程序员历史上的今天... 📡"))
        )
        
        # 调用API获取数据
        api_url = "https://uapis.cn/api/v1/history/programmer/today"
        
        # 设置超时
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # 删除加载提示
                        await actions.del_message(loading_msg.data.message_id)
                        
                        if data.get("message") == "获取成功" and data.get("events"):
                            events = data["events"]
                            today_date = datetime.now().strftime("%m月%d日")
                            
                            # 构建消息内容
                            message_content = [
                                header,
                                f"📅 今天是{today_date}，程序员历史上的今天：\n"
                            ]
                            
                            # 添加事件信息
                            for i, event_data in enumerate(events, 1):
                                year = event_data.get("year", "未知年份")
                                title = event_data.get("title", "无标题")
                                description = event_data.get("description", "")
                                category = event_data.get("category", "未知分类")
                                importance = event_data.get("importance", 0)
                                
                                # 根据重要性添加星星
                                stars = "⭐" * min(importance, 5)
                                
                                # 构建单条事件信息
                                event_info = f"{i}. 【{year}年】{title}"
                                if category != "未知分类":
                                    event_info += f" ({category})"
                                if stars:
                                    event_info += f" {stars}"
                                
                                message_content.append(event_info)
                                message_content.append(f"   📖 {description}")
                                
                                # 如果有标签，显示标签
                                tags = event_data.get("tags", [])
                                if tags:
                                    tags_str = " | ".join(tags)
                                    message_content.append(f"   🏷️ 标签：{tags_str}")
                                
                                message_content.append("")
                            
                            # 添加统计信息
                            message_content.append(f"✨ 共找到 {len(events)} 个相关历史事件")
                            
                            # 发送消息
                            full_message = "\n".join(message_content)
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text(full_message))
                            )
                            
                        else:
                            # API返回数据但无事件
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text(
                                    f"{header}\n"
                                    f"今天（{datetime.now().strftime('%m月%d日')}）没有找到程序员相关的历史事件记录。\n"
                                    "也许今天正是创造历史的好时机！🚀"
                                ))
                            )
                    
                    else:
                        # 删除加载提示
                        await actions.del_message(loading_msg.data.message_id)
                        
                        # API请求失败
                        await actions.send(
                            group_id=event.group_id,
                            message=Manager.Message(Segments.Text(
                                f"{header}\n"
                                f"❌ 获取历史事件失败（HTTP {response.status}）\n"
                                "请稍后再试，或联系管理员检查网络连接。"
                            ))
                        )
                        
            except asyncio.TimeoutError:
                # 删除加载提示
                await actions.del_message(loading_msg.data.message_id)
                
                await actions.send(
                    group_id=event.group_id,
                    message=Manager.Message(Segments.Text(
                        f"{header}\n"
                        "⏰ 请求超时，请稍后再试。\n"
                        "服务器可能暂时无法响应，请耐心等待一会儿～"
                    ))
                )
                
            except aiohttp.ClientError as e:
                # 删除加载提示
                await actions.del_message(loading_msg.data.message_id)
                
                await actions.send(
                    group_id=event.group_id,
                    message=Manager.Message(Segments.Text(
                        f"{header}\n"
                        f"❌ 网络请求出错：{str(e)}\n"
                        "请稍后再试或联系管理员。"
                    ))
                )
                
    except Exception as e:
        # 处理其他异常
        error_msg = f"插件执行错误：{str(e)}"
        print(f"ProgrammerHistoryToday插件错误：{error_msg}")
        
        try:
            await actions.send(
                group_id=event.group_id,
                message=Manager.Message(Segments.Text(
                    f"{header}\n"
                    "😢 插件执行时出现意外错误，请稍后再试。"
                ))
            )
        except:
            pass
    
    return True  # 阻断后续插件执行