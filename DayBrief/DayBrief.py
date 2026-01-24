import aiohttp
import asyncio
import tempfile
import os
from datetime import datetime

# 导入配置管理模块
from Hyper import Configurator
Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())

reminder = Configurator.cm.get_cfg().others["reminder"]

TRIGGHT_KEYWORD = "日新闻图"
HELP_MESSAGE = f"{reminder}日新闻图 —> 获取今日新闻摘要图片 📰"

async def on_message(event, actions, Manager, Segments):
    try:
        message_text = str(event.message)
        if not message_text.startswith(f"{reminder}日新闻图"):
            return None
            
        api_url = "https://uapis.cn/api/v1/daily/news-image"
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '')
                        if 'image' in content_type or 'jpeg' in content_type.lower():
                            temp_file = tempfile.NamedTemporaryFile(
                                suffix='.jpg',
                                delete=False,
                                prefix=f'news_{datetime.now().strftime("%Y%m%d")}_'
                            )
                            temp_path = temp_file.name
                            temp_file.close()
                            
                            image_data = await response.read()
                            with open(temp_path, 'wb') as f:
                                f.write(image_data)
                            
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Image(temp_path))
                            )
                            
                            try:
                                os.unlink(temp_path)
                            except:
                                pass
                            
                            return True
                        else:
                            error_text = await response.text()
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text(f"接口返回非图片数据:\n{error_text[:200]}"))
                            )
                            return True
                    
                    elif response.status == 500:
                        try:
                            error_data = await response.json()
                            error_msg = error_data.get('message', '未知错误')
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text(f"服务器内部错误:\n{error_msg}"))
                            )
                        except:
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text("服务器内部错误，请稍后重试"))
                            )
                        return True
                    
                    elif response.status == 502:
                        try:
                            error_data = await response.json()
                            error_msg = error_data.get('message', '未知错误')
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text(f"新闻源获取失败:\n{error_msg}\n请稍后重试"))
                            )
                        except:
                            await actions.send(
                                group_id=event.group_id,
                                message=Manager.Message(Segments.Text("新闻源获取失败，请稍后重试"))
                            )
                        return True
                    
                    else:
                        await actions.send(
                            group_id=event.group_id,
                            message=Manager.Message(Segments.Text(f"请求失败，状态码: {response.status}"))
                        )
                        return True
                        
            except asyncio.TimeoutError:
                await actions.send(
                    group_id=event.group_id,
                    message=Manager.Message(Segments.Text("请求超时，新闻生成时间较长，请稍后重试"))
                )
                return True
                
            except aiohttp.ClientError as e:
                await actions.send(
                    group_id=event.group_id,
                    message=Manager.Message(Segments.Text(f"网络请求出错：{str(e)}"))
                )
                return True
                
    except Exception as e:
        await actions.send(
            group_id=event.group_id,
            message=Manager.Message(Segments.Text("插件执行时出现意外错误，请稍后再试"))
        )
        return True