import os
import re
import time
import json
import asyncio
import aiohttp
import threading
from collections import deque
from datetime import datetime
from typing import Dict, List, Set, Optional
from Hyper import Configurator

# 加载配置
Configurator.cm = Configurator.ConfigManager(Configurator.Config(file="config.json").load_from_file())
config = Configurator.cm.get_cfg()

try:
    reminder = config.others["reminder"]
except (KeyError, AttributeError):
    print("[敏感词检测] 错误: 配置文件中未找到 'reminder' 字段")
    raise

try:
    bot_name = config.others["bot_name"]
except (KeyError, AttributeError):
    print("[敏感词检测] 错误: 配置文件中未找到 'bot_name' 字段")
    raise

TRIGGHT_KEYWORD = "Any"  # 永久触发插件

# 一级菜单
HELP_MESSAGE = f"""{reminder}敏感词检测 开启/关闭/状态 —> 🌟 管理群内敏感词检测功能
{reminder}敏感词检测 —> 查看详细使用方式"""

# 二级菜单（详细版）- 用于详细帮助显示
SECONDARY_HELP = f"""{reminder}敏感词检测 开启/关闭/状态 —> 🌟 管理群内敏感词检测功能
{reminder}敏感词检测 添加敏感词 [敏感词] —> 📝 添加新的敏感词
{reminder}敏感词检测 删除敏感词 [敏感词] —> 🗑️ 删除现有敏感词
{reminder}敏感词检测 添加白名单 [QQ号] —> 🛡️ 添加用户到白名单
{reminder}敏感词检测 删除白名单 [QQ号] —> 📤 从白名单移除用户
{reminder}敏感词检测 重置用户违规 [QQ号] —> 🔄 重置用户的违规记录
{reminder}敏感词检测 查看违规记录 [QQ号] —> 📊 查看用户的违规记录
{reminder}敏感词检测 设置 窗口时间 [秒数] —> ⏰ 设置违规统计窗口时间
{reminder}敏感词检测 设置 最大违规 [次数] —️> ⚠️ 设置最大违规次数
{reminder}敏感词检测 设置 禁言时长 [秒数] —> 🔇 设置禁言时长"""

# 数据存储路径
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sensitive_words")
os.makedirs(DATA_DIR, exist_ok=True)

# 文件路径
ENABLED_GROUPS_FILE = os.path.join(DATA_DIR, "enabled_groups.json")
LOCAL_WORDS_FILE = os.path.join(DATA_DIR, "sensitive_words.txt")
WHITELIST_FILE = os.path.join(DATA_DIR, "whitelist.txt")
VIOLATION_RECORDS_FILE = os.path.join(DATA_DIR, "violation_records.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# 默认配置
DEFAULT_CONFIG = {
    "warning_cooldown": 20,  # 警告消息20秒后撤回
    "violation_window": 60,  # 违规计数窗口（秒）
    "max_violations": 10,  # 最大违规次数
    "ban_duration": 600,  # 禁言时长（秒）- 10分钟
    "check_images": False  # 是否检查图片消息
}

# AC自动机类
class AhoCorasick:
    """AC自动机 - 多模式字符串匹配算法"""
    
    class TrieNode:
        def __init__(self):
            self.children = {}  # 子节点字典
            self.fail = None    # 失败指针
            self.is_end = False # 是否为模式串结尾
            self.word = None    # 对应的敏感词
            self.output = []    # 输出列表（用于包含更短的敏感词）
    
    def __init__(self):
        self.root = self.TrieNode()
        self.is_built = False
        self.word_count = 0
    
    def add_word(self, word: str):
        """添加敏感词到Trie树"""
        if not word:
            return
        
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = self.TrieNode()
            node = node.children[char]
        
        if not node.is_end:  # 避免重复计数
            node.is_end = True
            node.word = word
            self.word_count += 1
        
        self.is_built = False
    
    def build_fail(self):
        """构建失败指针（BFS算法）"""
        queue = deque()
        
        # 第一层节点的fail指向root
        for child in self.root.children.values():
            child.fail = self.root
            queue.append(child)
        
        # BFS构建失败指针
        while queue:
            current_node = queue.popleft()
            
            # 遍历当前节点的所有子节点
            for char, child_node in current_node.children.items():
                queue.append(child_node)
                
                # 从当前节点的fail节点开始寻找
                fail_node = current_node.fail
                
                # 不断回溯直到找到有char子节点的节点或到达root
                while fail_node is not None and char not in fail_node.children:
                    fail_node = fail_node.fail
                
                if fail_node is None:
                    child_node.fail = self.root
                else:
                    child_node.fail = fail_node.children[char]
                    
                    # 如果fail节点是结束节点，将对应的敏感词添加到output中
                    if child_node.fail.is_end:
                        child_node.output.append(child_node.fail.word)
        
        self.is_built = True
    
    def search(self, text: str) -> List[str]:
        """搜索文本中匹配的敏感词"""
        if not text or not self.word_count or not self.is_built:
            return []
        
        matched = set()
        current_node = self.root
        
        for i, char in enumerate(text):
            # 如果当前字符不在子节点中，沿着失败指针回溯
            while current_node != self.root and char not in current_node.children:
                current_node = current_node.fail
            
            # 如果字符在当前节点的子节点中，移动到该子节点
            if char in current_node.children:
                current_node = current_node.children[char]
                
                # 检查当前节点是否为结束节点
                if current_node.is_end:
                    matched.add(current_node.word)
                
                # 检查输出列表中的敏感词（包含更短的敏感词）
                for word in current_node.output:
                    matched.add(word)
        
        return list(matched)

# 全局存储结构
enabled_groups = {}  # 存储启用了敏感词检测的群
local_words = set()  # 本地敏感词库
whitelist = set()  # 白名单用户
violation_records = {}  # 违规记录 {group_id: {user_id: {count: x, first_time: t, last_time: t, messages: []}}}
cooldown_data = {}  # 存储禁言中的用户 {group_id: {user_id: end_time}}
plugin_config = DEFAULT_CONFIG.copy()
admin_list = []  # 管理员列表缓存
data_loaded = False  # 数据加载标志

# AC自动机实例
ac_automaton = AhoCorasick()

# 敏感词检测API设置
SENSITIVE_WORD_API = "https://uapis.cn/api/v1/text/profanitycheck"
REQUEST_TIMEOUT = 10

def load_all_data():
    """一次性加载所有数据"""
    global enabled_groups, local_words, whitelist, violation_records, plugin_config, admin_list, data_loaded
    
    if data_loaded:
        return
    
    # 加载群组配置
    try:
        if os.path.exists(ENABLED_GROUPS_FILE):
            with open(ENABLED_GROUPS_FILE, 'r', encoding='utf-8') as f:
                enabled_groups = json.load(f)
    except Exception as e:
        print(f"[敏感词检测] 加载群组配置失败: {e}")
        enabled_groups = {}
    
    # 加载本地敏感词
    load_local_words()
    
    # 加载白名单
    try:
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, 'r', encoding='utf-8') as f:
                whitelist.clear()
                for line in f:
                    user_id = line.strip()
                    if user_id and not user_id.startswith('#'):
                        whitelist.add(user_id)
    except Exception as e:
        print(f"[敏感词检测] 加载白名单失败: {e}")
        whitelist = set()
    
    # 加载违规记录
    try:
        if os.path.exists(VIOLATION_RECORDS_FILE):
            with open(VIOLATION_RECORDS_FILE, 'r', encoding='utf-8') as f:
                violation_records = json.load(f)
    except Exception as e:
        print(f"[敏感词检测] 加载违规记录失败: {e}")
        violation_records = {}
    
    # 加载插件配置
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                plugin_config.update(loaded_config)
    except Exception as e:
        print(f"[敏感词检测] 加载插件配置失败: {e}")
        plugin_config = DEFAULT_CONFIG.copy()
    
    # 加载管理员列表
    admin_list = get_admins()
    
    data_loaded = True

def get_admins():
    """获取所有管理员用户列表（ROOT_User + Super_User + Manage_User）"""
    try:
        # 从配置文件获取root用户
        root_users = []
        if hasattr(config, 'owner'):
            root_users = [str(uid) for uid in getattr(config, 'owner', [])]
        elif hasattr(config, 'others') and 'ROOT_User' in config.others:
            root_users = config.others.get('ROOT_User', [])
        
        # 加载Super_User列表
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
        
        # 加载Super_User和Manage_User
        super_users = load_user_list("Super_User.ini")
        manage_users = load_user_list("Manage_User.ini")
        
        # 合并所有管理员
        all_admins = []
        all_admins.extend(root_users)
        all_admins.extend(super_users)
        all_admins.extend(manage_users)
        
        # 去重后返回
        return list(set(all_admins))
    except Exception as e:
        print(f"[敏感词检测] 获取管理员列表失败: {e}")
        return []

def is_admin_user(user_id: int) -> bool:
    """检查用户是否为管理员（ROOT_User/Super_User/Manage_User）"""
    return str(user_id) in admin_list

def load_local_words():
    """加载本地敏感词并构建AC自动机"""
    global local_words, ac_automaton
    
    try:
        if os.path.exists(LOCAL_WORDS_FILE):
            # 重新初始化AC自动机
            ac_automaton = AhoCorasick()
            local_words.clear()
            
            with open(LOCAL_WORDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith('#'):
                        local_words.add(word)
                        ac_automaton.add_word(word.lower())
                
                # 构建AC自动机的失败指针
                ac_automaton.build_fail()
    except Exception as e:
        print(f"[敏感词检测] 加载本地敏感词失败: {e}")
        local_words = set()

def refresh_ac_automaton():
    """根据当前local_words重建AC自动机"""
    global ac_automaton
    
    ac_automaton = AhoCorasick()
    for word in local_words:
        ac_automaton.add_word(word.lower())
    ac_automaton.build_fail()

def save_local_words():
    """保存本地敏感词"""
    try:
        with open(LOCAL_WORDS_FILE, 'w', encoding='utf-8') as f:
            for word in sorted(local_words):
                f.write(word + "\n")
    except Exception as e:
        print(f"[敏感词检测] 保存本地敏感词失败: {e}")

def save_enabled_groups():
    """保存已启用的群组"""
    try:
        with open(ENABLED_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(enabled_groups, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[敏感词检测] 保存群组配置失败: {e}")

def save_whitelist():
    """保存白名单"""
    try:
        with open(WHITELIST_FILE, 'w', encoding='utf-8') as f:
            for user_id in sorted(whitelist):
                f.write(user_id + "\n")
    except Exception as e:
        print(f"[敏感词检测] 保存白名单失败: {e}")

def save_violation_records():
    """保存违规记录"""
    try:
        with open(VIOLATION_RECORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(violation_records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[敏感词检测] 保存违规记录失败: {e}")

def save_plugin_config():
    """保存插件配置"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(plugin_config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[敏感词检测] 保存插件配置失败: {e}")

def is_text_message(message) -> bool:
    """检查消息是否为文本消息"""
    try:
        msg_str = str(message)
        # 检查是否有文本内容（去除CQ码后是否有非空字符）
        cleaned_msg = re.sub(r'\[.*?\]', '', msg_str)
        return bool(cleaned_msg.strip())
    except:
        return False

def extract_text_from_message(message) -> str:
    """从消息中提取纯文本"""
    try:
        msg_str = str(message)
        # 移除各种CQ码
        cleaned_msg = re.sub(r'\[.*?\]', '', msg_str)
        return cleaned_msg.strip()
    except:
        return ""

def check_local_sensitive_words(text: str) -> List[str]:
    """使用AC自动机检查本地敏感词并返回匹配的词列表"""
    if not text:
        return []
    
    # 统一转为小写进行匹配
    text_lower = text.lower()
    return ac_automaton.search(text_lower)

async def check_api_sensitive_word(text: str) -> Dict:
    """调用API检测敏感词"""
    if not text:
        return {"status": "error", "message": "文本为空"}
    
    headers = {"Content-Type": "application/json"}
    data = {"text": text}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SENSITIVE_WORD_API, json=data, headers=headers, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    return {"status": "error", "message": f"API请求失败: {response.status}"}
    except asyncio.TimeoutError:
        return {"status": "error", "message": "API请求超时"}
    except Exception as e:
        return {"status": "error", "message": f"网络错误: {str(e)}"}

async def safe_delete_message(actions, message_id: int) -> bool:
    """安全删除消息，避免超时错误"""
    try:
        # 添加超时限制
        await asyncio.wait_for(actions.del_message(message_id), timeout=5.0)
        return True
    except asyncio.TimeoutError:
        return False
    except Exception as e:
        error_msg = str(e).lower()
        # 忽略特定的错误类型
        if "timeout" in error_msg or "already recalled" in error_msg or "已被撤回" in error_msg:
            return True  # 返回True表示可以继续处理
        else:
            return False

async def schedule_message_deletion(sent_msg, actions, delay: int = None):
    """安排消息在指定时间后删除"""
    if delay is None:
        delay = plugin_config["warning_cooldown"]
    
    try:
        # 获取消息ID的不同方式
        message_id = None
        
        # 方式1：直接从返回值中获取
        if hasattr(sent_msg, 'message_id'):
            message_id = sent_msg.message_id
        elif hasattr(sent_msg, 'data') and hasattr(sent_msg.data, 'message_id'):
            message_id = sent_msg.data.message_id
        # 方式2：尝试解析返回值
        elif isinstance(sent_msg, dict) and 'message_id' in sent_msg:
            message_id = sent_msg['message_id']
        
        if not message_id:
            return
        
        def delete_message_sync():
            """同步删除消息的线程函数"""
            try:
                # 等待指定时间
                time.sleep(delay)
                
                # 创建新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def delete():
                    """异步删除消息"""
                    try:
                        await safe_delete_message(actions, message_id)
                    except Exception:
                        pass
                
                # 运行删除任务
                loop.run_until_complete(delete())
                loop.close()
                
            except Exception:
                pass
        
        # 创建并启动删除线程
        thread = threading.Thread(target=delete_message_sync, daemon=True)
        thread.start()
                    
    except Exception:
        pass

async def send_message_with_auto_delete(actions, group_id, message, delay: int = None):
    """发送消息并安排自动撤回"""
    if delay is None:
        delay = plugin_config["warning_cooldown"]
    
    try:
        # 发送消息
        sent_msg = await actions.send(group_id=group_id, message=message)
        
        if sent_msg:
            # 安排自动删除
            asyncio.create_task(schedule_message_deletion(sent_msg, actions, delay))
            return sent_msg
        else:
            return None
            
    except Exception as e:
        print(f"[敏感词检测] 发送消息失败: {e}")
        return None

def update_violation_record(group_id: int, user_id: int, message_text: str, message_id: int):
    """更新违规记录"""
    group_key = str(group_id)
    user_key = str(user_id)
    current_time = time.time()
    
    # 初始化数据结构
    if group_key not in violation_records:
        violation_records[group_key] = {}
    
    if user_key not in violation_records[group_key]:
        violation_records[group_key][user_key] = {
            "count": 0,
            "first_time": current_time,
            "last_time": current_time,
            "messages": []
        }
    
    user_record = violation_records[group_key][user_key]
    
    # 清理过期的违规记录（超过统计窗口）
    window = plugin_config["violation_window"]
    if current_time - user_record["first_time"] > window:
        user_record["count"] = 0
        user_record["first_time"] = current_time
        user_record["messages"] = []
    
    # 更新记录
    user_record["count"] += 1
    user_record["last_time"] = current_time
    user_record["messages"].append({
        "time": current_time,
        "text": message_text[:100],  # 只保存前100个字符
        "message_id": message_id
    })
    
    # 限制保存的消息数量
    if len(user_record["messages"]) > plugin_config["max_violations"]:
        user_record["messages"] = user_record["messages"][-plugin_config["max_violations"]:]
    
    # 保存到文件
    save_violation_records()
    
    return user_record["count"]

def check_should_ban(group_id: int, user_id: int) -> bool:
    """检查是否应该禁言用户"""
    group_key = str(group_id)
    user_key = str(user_id)
    
    if group_key not in violation_records or user_key not in violation_records[group_key]:
        return False
    
    user_record = violation_records[group_key][user_key]
    current_time = time.time()
    
    # 检查是否在时间窗口内达到最大违规次数
    if (user_record["count"] >= plugin_config["max_violations"] and 
        current_time - user_record["first_time"] <= plugin_config["violation_window"]):
        return True
    
    return False

def reset_violation_record(group_id: int, user_id: int):
    """重置用户的违规记录"""
    group_key = str(group_id)
    user_key = str(user_id)
    
    if group_key in violation_records and user_key in violation_records[group_key]:
        del violation_records[group_key][user_key]
        if not violation_records[group_key]:
            del violation_records[group_key]
        save_violation_records()

async def ban_user(actions, group_id: int, user_id: int, duration: int = None):
    """禁言用户"""
    if duration is None:
        duration = plugin_config["ban_duration"]
    
    try:
        await actions.set_group_ban(
            group_id=group_id,
            user_id=user_id,
            duration=duration
        )
        
        # 记录禁言时间
        if str(group_id) not in cooldown_data:
            cooldown_data[str(group_id)] = {}
        cooldown_data[str(group_id)][str(user_id)] = time.time() + duration
        
        return True
    except Exception as e:
        print(f"[敏感词检测] 禁言失败: {e}")
        return False

async def on_message(event, actions, Manager, Segments, Events, reminder):
    """处理消息事件"""
    # 只处理群消息事件
    if not isinstance(event, Events.GroupMessageEvent):
        return False
    
    # 确保数据已加载（只在第一次加载）
    if not data_loaded:
        load_all_data()
    
    # 跳过机器人自己的消息
    if event.user_id == event.self_id:
        return False
    
    # 获取消息内容
    message_text = str(event.message)
    group_id = event.group_id
    user_id = event.user_id
    
    # 只处理文本消息
    if not is_text_message(message_text):
        return False
    
    # 提取纯文本内容
    clean_text = extract_text_from_message(message_text)
    if not clean_text:
        return False
    
    # 处理管理员的命令 - 使用配置中的reminder作为前缀
    if clean_text.startswith(f"{reminder}敏感词检测"):
        # 检查用户是否为管理员
        if not is_admin_user(user_id):
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Text("⚠️ 只有管理员可以使用此命令哦~ (･ω<)☆"))
            )
            return True
        
        # 移除前缀和命令名，获取具体命令
        command_text = clean_text[len(f"{reminder}敏感词检测"):].strip()
        
        if not command_text:
            # 当用户只发送"{reminder}敏感词检测"时，显示二级菜单
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Text(
                    f"📚 【{bot_name}敏感词检测详细使用方式】\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{SECONDARY_HELP}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💝 {bot_name}会认真守护聊天环境哦~"
                ))
            )
            return True
        
        # 开启检测
        if command_text in ["开启", "true", "on", "enable"]:
            enabled_groups[str(group_id)] = True
            save_enabled_groups()
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Text(
                    f"🎉 已在当前群开启敏感词检测功能！\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✨ {bot_name}需要管理员权限才能撤回消息哦~\n"
                    f"⚠️ 违规规则：\n"
                    f"  • {plugin_config['violation_window']}秒内\n"
                    f"  • 违规{plugin_config['max_violations']}次\n"
                    f"  • 将禁言{plugin_config['ban_duration']//60}分钟\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💡 管理员和白名单用户不受限制~"
                ))
            )
            return True
        
        # 关闭检测
        elif command_text in ["关闭", "false", "off", "disable"]:
            if str(group_id) in enabled_groups:
                del enabled_groups[str(group_id)]
                save_enabled_groups()
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Text("🔒 已在当前群关闭敏感词检测功能 (。-ω-)zzz"))
            )
            return True
        
        # 查看状态
        elif command_text in ["状态", "status"]:
            status = "✅ 开启" if str(group_id) in enabled_groups else "❌ 关闭"
            local_count = len(local_words)
            whitelist_count = len(whitelist)
            
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Text(
                    f"📋 【{bot_name}敏感词检测状态】\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔸 当前群状态: {status}\n"
                    f"🔸 本地敏感词: {local_count} 个\n"
                    f"🔸 白名单用户: {whitelist_count} 个\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚙️ 当前设置：\n"
                    f"  • 违规窗口: {plugin_config['violation_window']}秒\n"
                    f"  • 最大违规: {plugin_config['max_violations']}次\n"
                    f"  • 禁言时长: {plugin_config['ban_duration']//60}分钟\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📖 使用帮助：\n"
                    f"{HELP_MESSAGE}"
                ))
            )
            return True
        
        # 添加敏感词
        elif command_text.startswith("添加敏感词 "):
            word = command_text[6:].strip()
            if word:
                if word not in local_words:
                    local_words.add(word)
                    save_local_words()
                    # 重新构建AC自动机
                    refresh_ac_automaton()
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"✅ 已成功添加敏感词: 【{word}】 (＾∀＾)ﾉ"))
                    )
                else:
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"⚠️ 敏感词 【{word}】 已经存在啦~ (´• ω •`)ﾉ"))
                    )
            else:
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text("❌ 请输入要添加的敏感词哦~ (＞﹏＜)"))
                )
            return True
        
        # 删除敏感词
        elif command_text.startswith("删除敏感词 "):
            word = command_text[6:].strip()
            if word:
                if word in local_words:
                    local_words.remove(word)
                    save_local_words()
                    # 重新构建AC自动机
                    refresh_ac_automaton()
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"✅ 已成功删除敏感词: 【{word}】 (´∀｀)♡"))
                    )
                else:
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"⚠️ 敏感词 【{word}】 不存在呢~ (´･ω･`?)"))
                    )
            else:
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text("❌ 请输入要删除的敏感词哦~ (；´д｀)ゞ"))
                )
            return True
        
        # 添加白名单
        elif command_text.startswith("添加白名单 "):
            user = command_text[6:].strip()
            if user.isdigit():
                if user not in whitelist:
                    whitelist.add(user)
                    save_whitelist()
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"✅ 已成功添加白名单用户: {user} 🛡️ (＾▽＾)"))
                    )
                else:
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"⚠️ 用户 {user} 已经在白名单里啦~ (￣▽￣)~*"))
                    )
            else:
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text("❌ 请输入有效的QQ号哦~ (；´д｀)ゞ"))
                )
            return True
        
        # 删除白名单
        elif command_text.startswith("删除白名单 "):
            user = command_text[6:].strip()
            if user.isdigit():
                if user in whitelist:
                    whitelist.remove(user)
                    save_whitelist()
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"✅ 已成功删除白名单用户: {user} 📤 (´• ω •`)ﾉ"))
                    )
                else:
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"⚠️ 用户 {user} 不在白名单中呢~ (´･ω･`?)"))
                    )
            else:
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text("❌ 请输入有效的QQ号哦~ (＞﹏＜)"))
                )
            return True
        
        # 重置用户违规记录
        elif command_text.startswith("重置用户违规 "):
            user = command_text[7:].strip()
            if user.isdigit():
                reset_violation_record(group_id, int(user))
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text(f"🔄 已重置用户 {user} 的违规记录 (＾∀＾)ﾉ"))
                )
            else:
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text("❌ 请输入有效的QQ号哦~ (；´д｀)ゞ"))
                )
            return True
        
        # 查看违规记录
        elif command_text.startswith("查看违规记录 "):
            user = command_text[7:].strip()
            if user.isdigit():
                group_key = str(group_id)
                user_key = user
                
                if group_key in violation_records and user_key in violation_records[group_key]:
                    record = violation_records[group_key][user_key]
                    messages = "\n".join([f"  {i+1}. {datetime.fromtimestamp(msg['time']).strftime('%H:%M:%S')}: {msg['text']}" 
                                        for i, msg in enumerate(record['messages'][-5:])])  # 只显示最近5条
                    
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(
                            f"📝 【用户 {user} 的违规记录】\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🔸 违规次数: {record['count']} 次\n"
                            f"🔸 首次违规: {datetime.fromtimestamp(record['first_time']).strftime('%H:%M:%S')}\n"
                            f"🔸 最近违规: {datetime.fromtimestamp(record['last_time']).strftime('%H:%M:%S')}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📋 最近违规内容:\n{messages}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 违规规则: {plugin_config['violation_window']}秒内"
                            f"违规{plugin_config['max_violations']}次将禁言"
                            f"{plugin_config['ban_duration']//60}分钟"
                        ))
                    )
                else:
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"💫 用户 {user} 没有违规记录呢，真是个乖宝宝~ (｡♥‿♥｡)"))
                    )
            else:
                await send_message_with_auto_delete(
                    actions,
                    group_id,
                    Manager.Message(Segments.Text("❌ 请输入有效的QQ号哦~ (＞﹏＜)"))
                )
            return True
        
        # 设置参数
        elif command_text.startswith("设置 "):
            parts = command_text[3:].split()
            if len(parts) >= 2:
                param = parts[0]
                value = parts[1]
                
                try:
                    if param == "窗口时间" and value.isdigit():
                        plugin_config["violation_window"] = int(value)
                        await send_message_with_auto_delete(
                            actions,
                            group_id,
                            Manager.Message(Segments.Text(f"⏰ 已设置违规窗口时间为 {value} 秒 (＾▽＾)"))
                        )
                    elif param == "最大违规" and value.isdigit():
                        plugin_config["max_violations"] = int(value)
                        await send_message_with_auto_delete(
                            actions,
                            group_id,
                            Manager.Message(Segments.Text(f"⚠️ 已设置最大违规次数为 {value} 次 (｀・ω・´)"))
                        )
                    elif param == "禁言时长" and value.isdigit():
                        plugin_config["ban_duration"] = int(value)
                        await send_message_with_auto_delete(
                            actions,
                            group_id,
                            Manager.Message(Segments.Text(f"🔇 已设置禁言时长为 {value} 秒 ({value//60} 分钟) (｀・ω・´)"))
                        )
                    else:
                        await send_message_with_auto_delete(
                            actions,
                            group_id,
                            Manager.Message(Segments.Text("❌ 无效的参数或值呢~ (；´д｀)ゞ"))
                        )
                except Exception as e:
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(f"❌ 设置失败: {str(e)[:30]}... (＞﹏＜)"))
                    )
                
                save_plugin_config()
                return True
        
        # 未知命令 - 显示二级菜单
        else:
            await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(Segments.Text(
                    f"🤔 未知的命令呢~ 试试这些命令吧：\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{SECONDARY_HELP}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💡 使用 {reminder}敏感词检测 查看完整帮助"
                ))
            )
            return True
    
    # 如果不是命令，检查是否启用了敏感词检测
    if str(group_id) not in enabled_groups:
        return False
    
    # 检查用户是否在管理员、白名单或特殊名单中
    user_key = str(user_id)
    
    # 1. 检查是否为管理员（ROOT_User/Super_User/Manage_User）
    if is_admin_user(user_id):
        # 管理员发言不受限制
        return False
    
    # 2. 检查是否在白名单中
    if user_key in whitelist:
        # 白名单用户发言不受限制
        return False
    
    # 检查用户是否在禁言冷却中
    group_key = str(group_id)
    if group_key in cooldown_data and user_key in cooldown_data[group_key]:
        if time.time() < cooldown_data[group_key][user_key]:
            # 用户正在禁言中，直接跳过
            return False
        else:
            # 禁言时间已过，清理记录
            del cooldown_data[group_key][user_key]
            if not cooldown_data[group_key]:
                del cooldown_data[group_key]
    
    # 检查本地敏感词（使用AC自动机）
    matched_local_words = check_local_sensitive_words(clean_text)
    
    # 检查API敏感词
    api_result = await check_api_sensitive_word(clean_text)
    matched_api_words = api_result.get("forbidden_words", []) if api_result.get("status") == "forbidden" else []
    
    # 如果没有敏感词，返回
    if not matched_local_words and not matched_api_words:
        return False
    
    print(f"[敏感词检测] 检测到敏感词，用户: {user_id}, 群: {group_id}")
    
    try:
        # 尝试撤回消息（使用安全删除）
        delete_success = await safe_delete_message(actions, event.message_id)
        
        if delete_success:
            print(f"[敏感词检测] 已撤回用户 {user_id} 的消息")
            
            # 更新违规记录
            violation_count = update_violation_record(group_id, user_id, clean_text, event.message_id)
            
            # 获取所有违规词
            all_forbidden_words = list(set(matched_local_words + matched_api_words))
            
            # 构建警告消息
            warning_parts = []
            
            # 使用正确的@方式
            warning_parts.append(Segments.At(user_id))
            warning_parts.append(Segments.Text(f" 检测到违规内容哦~ (｀・ω・´)\n"))
            
            warning_text = f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            warning_text += f"⚠️ 违规次数: {violation_count}/{plugin_config['max_violations']}\n"
            warning_text += f"⏰ 统计窗口: {plugin_config['violation_window']}秒\n"
            warning_text += f"🚫 禁言条件: {plugin_config['violation_window']}秒内违规{plugin_config['max_violations']}次\n"
            warning_text += f"🔇 禁言时长: {plugin_config['ban_duration']//60}分钟\n"
            
            if all_forbidden_words:
                warning_text += f"📋 违规词: {', '.join(all_forbidden_words[:3])}"
                if len(all_forbidden_words) > 3:
                    warning_text += f" 等{len(all_forbidden_words)}个词"
            
            warning_text += f"\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            warning_text += f"💡 请注意文明用语哦~ {bot_name}会守护聊天环境的！"
            
            warning_parts.append(Segments.Text(warning_text))
            
            # 发送警告消息
            warning_msg = await send_message_with_auto_delete(
                actions,
                group_id,
                Manager.Message(*warning_parts)
            )
            
            # 检查是否需要禁言
            if check_should_ban(group_id, user_id):
                ban_success = await ban_user(actions, group_id, user_id)
                
                if ban_success:
                    ban_notice = f"{Segments.At(user_id)} 因在{plugin_config['violation_window']}秒内触发{plugin_config['max_violations']}次违规词，{bot_name}已对你进行{plugin_config['ban_duration']//60}分钟禁言处理 🔇"
                    
                    await send_message_with_auto_delete(
                        actions,
                        group_id,
                        Manager.Message(Segments.Text(ban_notice))
                    )
                    
                    # 重置违规记录
                    reset_violation_record(group_id, user_id)
                    
                    print(f"[敏感词检测] 用户 {user_id} 已被禁言 {plugin_config['ban_duration']//60} 分钟")
        
        # 撤回失败时，保持静默，不发送任何提示
        
    except Exception as e:
        # 处理过程中出现异常，静默处理，只打印日志
        print(f"[敏感词检测] 处理敏感词失败: {str(e)[:100]}")
    
    return True

# 插件初始化
print("[敏感词检测插件] 正在初始化...")

# 加载数据
load_all_data()

print(f"[敏感词检测插件] 初始化完成")
print(f"  启用群组: {len(enabled_groups)} 个")
print(f"  本地敏感词: {len(local_words)} 个")
print(f"  白名单用户: {len(whitelist)} 个")
print(f"  管理员用户: {len(admin_list)} 个")
print(f"  违规窗口: {plugin_config['violation_window']}秒")
print(f"  最大违规: {plugin_config['max_violations']}次")
print(f"  禁言时长: {plugin_config['ban_duration']//60}分钟")