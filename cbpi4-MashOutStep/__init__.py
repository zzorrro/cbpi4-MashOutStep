import asyncio
import logging
from cbpi.api import *
from cbpi.api.config import ConfigType
from cbpi.api.base import CBPiBase
from cbpi.api.step import StepResult, CBPiStep
from cbpi.api.timer import Timer

logger = logging.getLogger(__name__)

class MashOutStep(CBPiStep):
    
    target_temp = NumberProperty("Target Temperature", default_value=76, description="Target temperature for MashOut")
    timer = NumberProperty("Timer (minutes)", default_value=10, description="Hold time in minutes")
    mash_stirrer_actor = ActorProperty("Mash Stirrer Actor", description="Actor to switch off (mash stirrer)")
    pump_actor = ActorProperty("Pump Actor", description="Actor to switch on (pump)")
    pump_delay = NumberProperty("Pump Delay (minutes)", default_value=2, description="Delay before pump starts (minutes)")
    
    async def on_start(self):
        """Действие при старте шага"""
        self.summary = "Starting MashOut..."
        await self.push_update()
        
        # Установить целевую температуру в котле
        await self.set_target_temperature(self.target_temp)
        
        # Отключить мешалку
        if self.mash_stirrer_actor:
            await self.actor_off(self.mash_stirrer_actor)
            logger.info(f"Mash stirrer (actor {self.mash_stirrer_actor}) switched off")
        
        # Запустить таймер (переводим минуты в секунды)
        timer_seconds = int(self.timer) * 60
        self.timer_instance = Timer(timer_seconds, self.on_timer_done, self.on_timer_update)
        self.timer_instance.start()
        
        # Запустить задержку перед включением насоса
        self.pump_started = False
        asyncio.create_task(self.start_pump_with_delay())
        
        await self.push_update()
    
    async def start_pump_with_delay(self):
        """Включить насос с задержкой"""
        delay_seconds = int(self.pump_delay) * 60  # Переводим минуты в секунды
        logger.info(f"Waiting {self.pump_delay} minutes ({delay_seconds} seconds) before starting pump...")
        await asyncio.sleep(delay_seconds)
        
        if self.pump_actor and not self.pump_started:
            await self.actor_on(self.pump_actor)
            self.pump_started = True
            logger.info(f"Pump (actor {self.pump_actor}) switched on after {self.pump_delay} minutes delay")
    
    async def on_timer_done(self, timer):
        """Действие при завершении таймера"""
        self.summary = "MashOut completed"
        await self.push_update()
        
        # Выключить насос при завершении
        if self.pump_actor and self.pump_started:
            await self.actor_off(self.pump_actor)
            logger.info(f"Pump (actor {self.pump_actor}) switched off")
        
        await self.next()
    
    async def on_timer_update(self, timer, seconds):
        """Обновление отображения таймера"""
        self.summary = f"{Timer.format_time(seconds)}"
        await self.push_update()
    
    async def on_stop(self):
        """Действие при остановке шага"""
        # Остановить таймер
        if hasattr(self, 'timer_instance'):
            self.timer_instance.stop()
        
        # Выключить насос
        if self.pump_actor and self.pump_started:
            await self.actor_off(self.pump_actor)
        
        await self.push_update()
    
    async def reset(self):
        """Сброс шага"""
        pass