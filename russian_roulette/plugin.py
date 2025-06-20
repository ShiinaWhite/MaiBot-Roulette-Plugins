import random
import asyncio
from typing import List, Tuple, Type, Optional, Dict
from datetime import datetime
from src.plugin_system import (BasePlugin, register_plugin, BaseCommand, ComponentInfo, ConfigField)
from src.common.logger import get_logger
from src.plugin_system.apis import chat_api

logger = get_logger("russian_roulette")

class RussianRouletteCommand(BaseCommand):
    command_name = "麦麦开枪"
    command_description = "参与麦麦轮盘游戏，随机禁言一名参与者。"
    command_pattern = r"^麦麦开枪$"
    command_help = "使用方法: 使用指令“麦麦开枪” - 开始游戏，参与者将被随机禁言。"
    command_examples = ["麦麦开枪"]
    intercept_message = True # 拦截消息，不让其他组件处理
    
    game_data: Dict = {}
    participants: List = []
    game_start_time: Optional[datetime] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 统一读取游戏配置参数
        self.max_wait_time = self.get_config("game_constants.max_wait_time", 120)
        self.max_participants = self.get_config("game_constants.max_participants", 6)
        self.min_mute_time = self.get_config("game_constants.min_mute_time", 60)
        self.max_mute_time = self.get_config("game_constants.max_mute_time", 3600)

    async def execute(self) -> Tuple[bool, str]:
        try:
            logger.info(f"{self.log_prefix} 开始执行麦麦开枪游戏命令") 
                       
            # 获取当前聊天流信息
            logger.info(f"{self.log_prefix} 尝试获取聊天流信息")
            chat_stream = self.message.chat_stream
            if not chat_stream:
                logger.info(f"{self.log_prefix} 获取聊天流信息失败")
                await self.send_text("获取聊天信息失败")
                return False, "获取聊天信息失败"
            
            # 检查是否在群聊中
            if chat_api.get_stream_type(chat_stream) != "group":
                await self.send_text("英雄的对决需要一个舞台，这场游戏只能在群聊的竞技场中上演。")
                return False, "非群聊环境"
            
            # 获取用户及群组信息
            user_id = str(chat_stream.user_info.user_id)
            user_name = chat_stream.user_info.user_nickname
            group_id = str(chat_stream.group_info.group_id)
            
            # 检查是否有正在进行的游戏
            game_key = f"{group_id}"
            current_time = datetime.now()
            if game_key in self.game_data:
                # 如果游戏已经开始超过最大等待时间，重置游戏
                elapsed_time = (current_time - self.game_data[game_key]["start_time"]).total_seconds()
                logger.info(f"{self.log_prefix} 游戏已进行 {elapsed_time} 秒")
                if elapsed_time > self.max_wait_time:
                    logger.info(f"{self.log_prefix} 游戏超时，重置游戏状态")
                    del self.game_data[game_key]
                else:                    
                    # 检查玩家是否已经参与
                    if user_id in [p["user_id"] for p in self.game_data[game_key]["participants"]]:
                        await self.send_text("命运的选择只有一次，勇敢的战士，你已经站在了这场游戏的舞台上。")
                        return False, "重复参与"
                        
                    # 添加新玩家
                    self.game_data[game_key]["participants"].append({
                        "user_id": user_id,
                        "user_name": user_name
                    })
                    
                    participants_count = len(self.game_data[game_key]["participants"])
                    # 提示参与信息
                    await self.send_text(f"米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，@{user_name} ( {participants_count} / {self.max_participants} )")
                    
                    # 如果达到最大参与人数或者最大参与人数为1，立即执行抽取
                    if participants_count >= self.max_participants or self.max_participants == 1:
                        logger.info(f"{self.log_prefix} 符合开枪条件 ({participants_count} / {self.max_participants})，开始执行抽取")
                        await self._execute_roulette(group_id)
                    
                    return True, "参与成功"
            else:
                # 创建新游戏并初始化游戏数据
                self.game_data[game_key] = {
                    "start_time": current_time,
                    "participants": [{
                        "user_id": user_id,
                        "user_name": user_name
                    }]
                }
                
                # 设置检查游戏状态的任务，仅在不是单人模式时设置
                if self.max_participants > 1:
                    asyncio.create_task(self._check_game_timeout(group_id))
                
                await self.send_text("这是一把充满荣耀与死亡的左轮手枪，六个弹槽只有一颗子弹，中弹的那个人将会被禁言。勇敢的战士们啊，扣动你们的扳机吧！")
                await asyncio.sleep(0.5)
                await self.send_text(f"米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，@{user_name} ( 1 / {self.max_participants} )")

                # 如果是单人模式，立即执行抽取
                if self.max_participants == 1:
                    await asyncio.sleep(1)  # 给用户一点时间看到加入消息
                    logger.info(f"{self.log_prefix} 单人模式，直接开始执行抽取")
                    await self._execute_roulette(group_id)
                
                return True, "游戏开始"
                
        except Exception as e:
            await self.send_text(f"发生错误：{str(e)}")
            return False, str(e)
    
    async def _execute_roulette(self, group_id: str):
        """执行轮盘抽取"""
        try:
            logger.info(f"{self.log_prefix} 开始执行轮盘抽取")
            if group_id not in self.game_data:
                logger.info(f"{self.log_prefix} 游戏数据已不存在，可能已被清理")
                return
                
            game = self.game_data[group_id]
            # 随机选择一个"幸运"的参与者
            unlucky_player = random.choice(game["participants"])
            # 随机禁言时间（秒）
            mute_seconds = random.randint(self.min_mute_time, self.max_mute_time)
            formatted_duration = self._format_duration(mute_seconds)
            
            logger.info(f"{self.log_prefix} 抽取到用户: {unlucky_player['user_name']}, 禁言时间: {formatted_duration}")
            await self.send_text(f"枪声响起，这个悲剧的主角早已注定......@{unlucky_player['user_name']} 成为了这段故事中的牺牲者。")
            await asyncio.sleep(5)  # 让子弹飞一会，给用户一点时间感受戏剧性
            
            # 执行禁言
            logger.info(f"{self.log_prefix} 开始执行禁言操作")
            success = await self.send_command(
                command_name="GROUP_BAN",
                args={
                    "qq_id": str(unlucky_player["user_id"]), 
                    "duration": str(mute_seconds)
                },
                storage_message=False
            )

            if not success:
                error_msg = "发送禁言命令失败"
                logger.info(f"{self.log_prefix} {error_msg}")
                await self.send_text("执行禁言操作失败")
            
            await self.send_text(f"命运无常，@{unlucky_player['user_name']} 将在{formatted_duration}的沉默中回味这一刻。")
            
            # 清理游戏数据
            del self.game_data[group_id]
            
        except Exception as e:
            logger.info(f"{self.log_prefix} 执行禁言时发生错误: {str(e)}", exc_info=True)
            await self.send_text(f"执行禁言时发生错误：{str(e)}")
    
    async def _check_game_timeout(self, group_id: str):
        """检查游戏是否超时"""
        logger.info(f"{self.log_prefix} 开始检查游戏超时 (群组: {group_id})")
        logger.info(f"{self.log_prefix} 等待 {self.max_wait_time} 秒后检查游戏状态")        
        remaining_time = self.max_wait_time
        logger.info(f"{self.log_prefix} 开始计时，每30秒记录一次状态，最后30秒内每10秒记录一次")

        # 记录剩余时间
        while remaining_time > 0:
            # 当剩余时间小于30秒时，每10秒记录一次
            log_interval = min(10 if remaining_time <= 30 else 30, remaining_time)
            await asyncio.sleep(log_interval)
            remaining_time -= log_interval
            
            if group_id in self.game_data:
                participants = self.game_data[group_id]["participants"]
                participants_count = len(participants)
                # 格式化参与者信息
                participants_info = "\n".join([
                    f"  - {p['user_name']}({p['user_id']})"
                    for p in participants
                ])
                formatted_remaining_time = self._format_duration(remaining_time)
                logger.info(
                    f"{self.log_prefix} 游戏状态更新:\n"
                    f"群组:{group_id}\n"
                    f"剩余时间: {formatted_remaining_time}\n"
                    f"当前参与人数: {participants_count}\n"
                    f"参与者列表:\n{participants_info}"
                )
        
        if group_id in self.game_data:
            game = self.game_data[group_id]
            if len(game["participants"]) > 0:
                # 如果还有参与者，执行抽取
                await self._execute_roulette(group_id)
            else:
                # 清理游戏数据
                del self.game_data[group_id]
    
    def _format_duration(self, seconds: int) -> str:
        """将秒数格式化为可读的时间字符串"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                return f"{minutes}分{remaining_seconds}秒"
            else:
                return f"{minutes}分钟"
        elif seconds < 86400:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes > 0:
                return f"{hours}小时{remaining_minutes}分钟"
            else:
                return f"{hours}小时"
        else:
            days = seconds // 86400
            remaining_hours = (seconds % 86400) // 3600
            if remaining_hours > 0:
                return f"{days}天{remaining_hours}小时"
            else:
                return f"{days}天"
            
@register_plugin
class RussianRoulettePlugin(BasePlugin):
    """麦麦轮盘游戏插件
    - 支持多人参与的开枪游戏
    - 支持自动禁言参与者
    - 支持游戏超时自动结束
    - 支持游戏状态检查
    - 完整的错误处理
    - 日志记录和监控
    """

    # 插件基本信息
    plugin_name = "russian_roulette"
    enable_plugin = True
    config_file_name = "config.toml"

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "logging": "日志记录配置",
    }

    # 配置Schema定义
    config_schema = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.0.0", description="插件配置文件版本号"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        # 游戏常量配置
        "game_constants": {
            "max_wait_time": ConfigField(type=int, default=120, description="最大等待时间（秒）"),
            "max_participants": ConfigField(type=int, default=6, description="最大参与人数"),
            "min_mute_time": ConfigField(type=int, default=60, description="最小禁言时间（秒）"),
            "max_mute_time": ConfigField(type=int, default=3600, description="最大禁言时间（秒）"),
        },
        "logging": {
            "level": ConfigField(
                type=str, default="INFO", description="日志级别", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            "prefix": ConfigField(type=str, default="[russian_roulette]", description="日志前缀"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""

        return [
            (RussianRouletteCommand.get_command_info(), RussianRouletteCommand),
        ]