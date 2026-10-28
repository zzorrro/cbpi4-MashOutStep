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

    @action("Добавить 5 минут к таймеру", [])
    async def add_timer(self):
        """Добавление 5 минут к работающему таймеру"""
        if self.timer.is_running == True:
            self.cbpi.notify(self.name, 'Добавлено 5 минут', NotificationType.INFO)
            await self.timer.add(300)       
        else:
            self.cbpi.notify(self.name, 'Таймер должен быть запущен, чтобы добавить время', NotificationType.WARNING)

    async def on_timer_done(self, timer):
        """Действие при завершении таймера выдержки"""
        self.summary = ""
        self.cbpi.notify(self.name, 'Мешаут завершен', NotificationType.SUCCESS)
        
        # Гарантированное отключение нагрева котла
        if self.kettle is not None:
            self.kettle.target_temp = 0
            try:
                await self.cbpi.kettle.set_target_temperature(self.kettle.id, 0)
            except Exception:
                pass
            
        # Выключаем насос
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
            
        await self.next()

    async def on_timer_update(self, timer, seconds):
        """Обновление отображения таймера в интерфейсе (только время)"""
        self.summary = Timer.format_time(seconds)
        await self.push_update()

    async def on_start(self):
        """Инициализация при запуске шага (в стиле BM_MashStep)"""
        self.port = str(self.cbpi.static_config.get('port', 8000))
        
        # 1. Получение параметров
        self.kettle = self.get_kettle(self.props.get("Kettle", None))
        self.sensor = self.props.get("Sensor", None)
        self.target_temp = float(self.props.get("Target Temp", 78))
        self.hold_time = int(self.props.get("Hold Time", 10))
        self.mash_stirrer = self.props.get("Mash Stirrer", None)
        self.pump = self.props.get("Pump", None)
        self.pump_delay = int(self.props.get("Pump Delay", 2))
        
        self.hold_time_seconds = self.hold_time * 60
        self.pump_delay_seconds = self.pump_delay * 60
        self.pump_started = False

        # 2. Устанавливаем целевую температуру через API котла (ЭТО ВАЖНО!)
        if self.kettle is not None:
            self.kettle.target_temp = int(self.target_temp)
            await self.cbpi.kettle.set_target_temperature(self.kettle.id, int(self.target_temp))
            logger.info(f"Установлена целевая температура {self.target_temp}°C для котла {self.kettle.id}")

        # 3. Отключаем мешалку при старте
        if self.mash_stirrer is not None:
            await self.actor_off(self.mash_stirrer)
            logger.info("Мешалка выключена")

        # 4. Инициализация таймера (пока не запускаем)
        if self.timer is None:
            self.timer = Timer(self.hold_time_seconds, on_update=self.on_timer_update, on_done=self.on_timer_done)

        # 5. Запускаем отложенное включение насоса в фоновой задаче
        asyncio.create_task(self.delayed_pump_start())

        self.summary = f"Нагрев до {self.target_temp}°C"
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
        
        # Гарантированное отключение нагрева
        if self.kettle is not None:
            self.kettle.target_temp = 0
            try:
                await self.cbpi.kettle.set_target_temperature(self.kettle.id, 0)
            except Exception:
                pass
            
        # Выключаем насос
        if self.pump is not None and self.pump_started:
            await self.actor_off(self.pump)
            
        await self.push_update()

    async def reset(self):
        """Сброс состояния шага"""
        self.hold_time = int(self.props.get("Hold Time", 10))
        self.timer = Timer(self.hold_time * 60, on_update=self.on_timer_update, on_done=self.on_timer_done)
        self.pump_started = False

    async def run(self):
        """Основной цикл выполнения шага (в стиле BM_MashStep)"""
        while self.running == True:
            await asyncio.sleep(1)
            
            sensor_data = self.get_sensor_value(self.sensor)
            if sensor_data and "value" in sensor_data:
                sensor_value = float(sensor_data.get("value"))
                
                # ЛОГИКА НАГРЕВА: ждем достижения целевой температуры
                if sensor_value >= self.target_temp and self.timer.is_running is not True:
                    self.timer.start()
                    self.timer.is_running = True
                    logger.info(f"Температура {sensor_value}°C достигнута, таймер запущен")
                        
            await self.push_update()
            
        return StepResult.DONE


def setup(cbpi):
    '''
    Этот метод вызывается сервером CBPI4 при запуске для регистрации плагина.
    '''
    cbpi.plugin.register("MashOutStep", MashOutStep)