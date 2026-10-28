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

    async def on_timer_done(self, timer):
        """Действие при завершении таймера выдержки"""
        self.summary = ""
        self.cbpi.notify(self.name, 'Мешаут завершен', NotificationType.SUCCESS)
        
        # Автоматически отключаем нагрев котла
        if self.kettle is not None:
            self.kettle.target_temp = 0
            await self.cbpi.kettle.set_target_temperature(self.kettle.id, 0)
            
        # Выключаем насос
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
            
        await self.next()

    async def on_timer_update(self, timer, seconds):
        """Обновление отображения таймера в интерфейсе"""
        self.summary = f"{Timer.format_time(seconds)}"
        await self.push_update()

    async def on_start(self):
        """Инициализация при запуске шага"""
        # 1. Получение параметров
        self.kettle = self.get_kettle(self.props.get("Kettle", None))
        self.sensor = self.props.get("Sensor", None)
        self.target_temp = float(self.props.get("Target Temp", 76))
        self.hold_time = int(self.props.get("Hold Time", 10))
        self.mash_stirrer = self.props.get("Mash Stirrer", None)
        self.pump = self.props.get("Pump", None)
        self.pump_delay = int(self.props.get("Pump Delay", 2))
        
        self.hold_time_seconds = self.hold_time * 60
        self.pump_delay_seconds = self.pump_delay * 60
        
        self.pump_started = False
        self.timer_started = False

        # 2. Отключаем мешалку при старте
        if self.mash_stirrer is not None:
            await self.actor_off(self.mash_stirrer)
            logger.info("Мешалка выключена")

        # 3. Устанавливаем целевую температуру котла
        if self.kettle is not None:
            await self.cbpi.kettle.set_target_temperature(self.kettle.id, self.target_temp)

        # 4. Инициализация таймера выдержки
        if self.timer is None:
            self.timer = Timer(self.hold_time_seconds, on_update=self.on_timer_update, on_done=self.on_timer_done)

        # 5. Запускаем отложенное включение насоса в фоновой задаче
        asyncio.create_task(self.delayed_pump_start())

        self.summary = f"Нагрев до {self.target_temp}°C..."
        await self.push_update()

    async def delayed_pump_start(self):
        """Фоновая задача для включения насоса с задержкой"""
        await asyncio.sleep(self.pump_delay_seconds)
        if self.running and self.pump is not None and not self.pump_started:
            await self.actor_on(self.pump)
            self.pump_started = True
            logger.info("Насос включен после задержки")
            self.cbpi.notify(self.name, 'Насос включен', NotificationType.INFO)
            await self.push_update()

    async def on_stop(self):
        """Действие при ручной остановке шага (безопасность)"""
        await self.timer.stop()
        self.summary = ""
        
        # Гарантированно выключаем нагрев котла
        if self.kettle is not None:
            self.kettle.target_temp = 0
            await self.cbpi.kettle.set_target_temperature(self.kettle.id, 0)
            
        # Гарантированно выключаем насос
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
            
        await self.push_update()

    async def reset(self):
        """Сброс состояния шага"""
        self.hold_time = int(self.props.get("Hold Time", 10))
        self.pump_delay = int(self.props.get("Pump Delay", 2))
        self.timer = Timer(self.hold_time * 60, on_update=self.on_timer_update, on_done=self.on_timer_done)
        self.pump_started = False
        self.timer_started = False

    async def run(self):
        """Основной цикл выполнения шага - отслеживает температуру и запускает таймер"""
        while self.running == True:
            await asyncio.sleep(1)
            
            # Получаем текущее значение температуры
            sensor_data = self.get_sensor_value(self.sensor)
            if sensor_data and "value" in sensor_data:
                current_temp = float(sensor_data.get("value"))
                
                # Если температура достигнута и таймер ещё не запущен
                if current_temp >= self.target_temp and not self.timer_started:
                    self.timer_started = True
                    self.timer.start()
                    self.timer.is_running = True
                    logger.info(f"Температура {current_temp}°C достигнута, таймер запущен")
            
            await self.push_update()
            
        return StepResult.DONE


def setup(cbpi):
    '''
    Этот метод вызывается сервером CBPI4 при запуске для регистрации плагина.
    '''
    cbpi.plugin.register("MashOutStep", MashOutStep)