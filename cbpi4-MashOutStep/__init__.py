import asyncio
import aiohttp
import logging
from datetime import datetime
import time
from cbpi.api import *
from cbpi.api.step import CBPiStep, StepResult
from cbpi.api.timer import Timer
from cbpi.api.dataclasses import NotificationType

logger = logging.getLogger(__name__)

@parameters([
    Property.Number(label="Timer", description="Time in Minutes", configurable=True), 
    Property.Number(label="Temp", configurable=True),
    Property.Sensor(label="Sensor"),
    Property.Kettle(label="Kettle"),
    Property.Select(label="AutoMode", options=["Yes", "No"], description="Switch Kettlelogic automatically on and off -> Yes"),
    Property.Actor(label="Mash Stirrer", description="Actor to switch OFF when target temp is reached"),
    Property.Actor(label="Pump", description="Actor to switch on with delay AFTER target temp is reached"),
    Property.Number(label="Pump Delay", description="Delay before pump starts (minutes) AFTER target temp", configurable=True)
])
class MashOutStep(CBPiStep):

    @action("START TIMER", [])
    async def start_timer(self):
        if self.timer.is_running is not True:
            self.cbpi.notify(self.name, 'Timer started', NotificationType.INFO)
            self.timer.start()
            self.timer.is_running = True
        else:
            self.cbpi.notify(self.name, 'Timer is already running', NotificationType.WARNING)

    @action("ADD 5 MINUTES TO TIMER", [])
    async def add_timer(self):
        if self.timer.is_running == True:
            self.cbpi.notify(self.name, '5 Minutes added', NotificationType.INFO)
            await self.timer.add(300)       
        else:
            self.cbpi.notify(self.name, 'Timer must be running to add time', NotificationType.WARNING)

    async def on_timer_done(self, timer):
        self.summary = ""
        if self.AutoMode == True:
            await self.setAutoMode(False)
        # Гарантированно выключаем насос и мешалку при завершении
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
        if self.mash_stirrer is not None:
            await self.actor_off(self.mash_stirrer)
            
        self.cbpi.notify(self.name, 'Step finished', NotificationType.SUCCESS)
        await self.next()

    async def on_timer_update(self, timer, seconds):
        self.summary = Timer.format_time(seconds)
        await self.push_update()

    async def on_start(self):
        self.port = str(self.cbpi.static_config.get('port', 8000))
        self.AutoMode = True if self.props.get("AutoMode", "No") == "Yes" else False
        self.kettle = self.get_kettle(self.props.Kettle)
        self.kettle.target_temp = int(self.props.get("Temp", 0))
        
        self.mash_stirrer = self.props.get("Mash Stirrer", None)
        self.pump = self.props.get("Pump", None)
        self.pump_delay = int(self.props.get("Pump Delay", 2))
        self.pump_delay_seconds = self.pump_delay * 60
        self.pump_started = False
        
        if self.AutoMode == True:
            await self.setAutoMode(True)
        
        # Мешалка уже работает с предыдущего этапа, ничего не делаем с ней на старте
        logging.info("MashOut step started, mash stirrer continues running")
        
        await self.push_update()

        if self.timer is None:
            self.timer = Timer(int(self.props.get("Timer", 0)) * 60, on_update=self.on_timer_update, on_done=self.on_timer_done)
        self.summary = "Waiting for Target Temp"
        
        await self.push_update()

    async def delayed_pump_start(self):
        # Задача ждет вызова после достижения температуры
        await asyncio.sleep(self.pump_delay_seconds)
        # Проверка self.running гарантирует безопасность при остановке шага
        if self.running and self.pump is not None and not self.pump_started:
            await self.actor_on(self.pump)
            self.pump_started = True
            logging.info("Pump switched on after delay")
            self.cbpi.notify(self.name, 'Pump switched on', NotificationType.INFO)
            await self.push_update()

    async def on_stop(self):
        await self.timer.stop()
        self.summary = ""
        if self.AutoMode == True:
            await self.setAutoMode(False)
        # Гарантированно выключаем насос и мешалку при ручной остановке
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
        if self.mash_stirrer is not None:
            await self.actor_off(self.mash_stirrer)
            
        await self.push_update()

    async def reset(self):
        self.timer = Timer(int(self.props.get("Timer", 0)) * 60, on_update=self.on_timer_update, on_done=self.on_timer_done)
        self.pump_started = False

    async def run(self):
        while self.running == True:
            await asyncio.sleep(1)
            sensor_value = self.get_sensor_value(self.props.get("Sensor", None)).get("value")
            
            # Проверяем достижение целевой температуры
            if sensor_value >= int(self.props.get("Temp", 0)) and self.timer.is_running is not True:
                
                # 1. Выключаем мешалку при достижении целевой температуры
                if self.mash_stirrer is not None:
                    await self.actor_off(self.mash_stirrer)
                    logging.info("Mash stirrer switched OFF at target temp")
                
                # 2. Запускаем задержку насоса (начинает отсчет СЕЙЧАС)
                asyncio.create_task(self.delayed_pump_start())
                
                # 3. Запускаем основной таймер выдержки
                self.timer.start()
                self.timer.is_running = True
                estimated_completion_time = datetime.fromtimestamp(time.time() + (int(self.props.get("Timer", 0))) * 60)
                self.cbpi.notify(self.name, 'Target temp reached. Timer started. Estimated completion: {}'.format(estimated_completion_time.strftime("%H:%M")), NotificationType.INFO)
                
        return StepResult.DONE

    async def setAutoMode(self, auto_state):
        try:
            # ВКЛЮЧЕНИЕ: если логика не запущена или выключена
            if (self.kettle.instance is None or self.kettle.instance.state == False) and (auto_state is True):
                url = "http://127.0.0.1:" + self.port + "/kettle/" + self.kettle.id + "/toggle"
                async with aiohttp.ClientSession() as session:
                    async with session.post(url) as response:
                        return await response.text()
            
            # ВЫКЛЮЧЕНИЕ: только если instance существует и сейчас включен
            # ИСПРАВЛЕНИЕ: добавлена проверка на None перед обращением к .state
            elif self.kettle.instance is not None and self.kettle.instance.state == True and (auto_state is False):
                await self.kettle.instance.stop()
                await self.push_update()
                
        except Exception as e:
            logging.error("Failed to switch KettleLogic {} {}".format(self.kettle.id, e))


def setup(cbpi):
    cbpi.plugin.register("MashOutStep", MashOutStep)
