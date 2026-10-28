import asyncio
import logging
from cbpi.api import *
from cbpi.api.step import CBPiStep, StepResult
from cbpi.api.timer import Timer
from cbpi.api.dataclasses import NotificationType

logger = logging.getLogger(__name__)

@parameters([
    Property.Kettle(label="Kettle", description="Варочный котел"),
    Property.Sensor(label="Sensor", description="Датчик температуры"),
    Property.Number(label="Target Temp", description="Целевая температура мешаута (°C)", configurable=True),
    Property.Number(label="Hold Time", description="Время выдержки в минутах", configurable=True),
    Property.Actor(label="Mash Stirrer", description="Актор мешалки (выкл. при старте)"),
    Property.Actor(label="Pump", description="Актор насоса (вкл. с задержкой)"),
    Property.Number(label="Pump Delay", description="Задержка перед включением насоса (мин)", configurable=True)
])
class MashOutStep(CBPiStep):

    @action("ADD 5 MINUTES TO TIMER", [])
    async def add_timer(self):
        if self.timer.is_running == True:
            self.cbpi.notify(self.name, 'Added 5 minutes to timer', NotificationType.INFO)
            await self.timer.add(300)       
        else:
            self.cbpi.notify(self.name, 'Timer must be running to add time', NotificationType.WARNING)

    async def on_timer_done(self, timer):
        self.summary = ""
        self.cbpi.notify(self.name, 'MashOut completed', NotificationType.SUCCESS)
        
        if self.kettle is not None:
            self.kettle.target_temp = 0
            try:
                await self.cbpi.kettle.set_target_temperature(self.kettle.id, 0)
            except Exception:
                pass
            
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
            
        await self.next()

    async def on_timer_update(self, timer, seconds):
        self.summary = Timer.format_time(seconds)
        await self.push_update()

    async def on_start(self):
        self.port = str(self.cbpi.static_config.get('port', 8000))
        
        # Получение параметров (как в BM_MashStep)
        self.kettle = self.get_kettle(self.props.Kettle)
        self.sensor = self.props.Sensor
        self.target_temp = int(self.props.get("Target Temp", 78))
        self.hold_time = int(self.props.get("Hold Time", 10))
        self.mash_stirrer = self.props.get("Mash Stirrer", None)
        self.pump = self.props.get("Pump", None)
        self.pump_delay = int(self.props.get("Pump Delay", 2))
        
        self.hold_time_seconds = self.hold_time * 60
        self.pump_delay_seconds = self.pump_delay * 60
        self.pump_started = False

        # Устанавливаем целевую температуру
        self.kettle.target_temp = self.target_temp
        await self.cbpi.kettle.set_target_temperature(self.kettle.id, self.target_temp)
        logger.info(f"Target temperature {self.target_temp}°C set for kettle {self.kettle.id}")

        # Отключаем мешалку
        if self.mash_stirrer is not None:
            await self.actor_off(self.mash_stirrer)
            logger.info("Mash stirrer switched off")

        # Инициализация таймера
        if self.timer is None:
            self.timer = Timer(self.hold_time_seconds, on_update=self.on_timer_update, on_done=self.on_timer_done)

        # Запускаем отложенное включение насоса
        asyncio.create_task(self.delayed_pump_start())

        self.summary = "Waiting for Target Temp"
        await self.push_update()

    async def delayed_pump_start(self):
        await asyncio.sleep(self.pump_delay_seconds)
        if self.running and self.pump is not None and not self.pump_started:
            await self.actor_on(self.pump)
            self.pump_started = True
            logger.info("Pump switched on after delay")
            self.cbpi.notify(self.name, 'Pump switched on', NotificationType.INFO)
            await self.push_update()

    async def on_stop(self):
        await self.timer.stop()
        self.summary = ""
        
        if self.kettle is not None:
            self.kettle.target_temp = 0
            try:
                await self.cbpi.kettle.set_target_temperature(self.kettle.id, 0)
            except Exception:
                pass
            
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
            
        await self.push_update()

    async def reset(self):
        self.hold_time = int(self.props.get("Hold Time", 10))
        self.timer = Timer(self.hold_time * 60, on_update=self.on_timer_update, on_done=self.on_timer_done)
        self.pump_started = False

    async def run(self):
        while self.running == True:
            await asyncio.sleep(1)
            
            # Получаем значение сенсора (как в BM_MashStep)
            sensor_value = self.get_sensor_value(self.sensor).get("value")
            
            if sensor_value >= self.target_temp and self.timer.is_running is not True:
                self.timer.start()
                self.timer.is_running = True
                logger.info(f"Temperature {sensor_value}°C reached, timer started")
                        
            await self.push_update()
            
        return StepResult.DONE


def setup(cbpi):
    cbpi.plugin.register("MashOutStep", MashOutStep)