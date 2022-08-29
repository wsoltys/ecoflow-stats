from datetime import timedelta
from typing import Any, Callable, Optional, TypeVar, cast

import reactivex.operators as ops
from reactivex import Observable, Subject, compose, throw
from reactivex.subject.replaysubject import ReplaySubject

import asyncio

import ecoflow as ef
from ecoflow import receive
from ecoflow.rxtcp import RxTcpAutoConnection

CONF_PRODUCT = "RIVER 600 Pro"
DISCONNECT_TIME = timedelta(seconds=15)
DOMAIN = "ecoflow"
CONF_EF = "192.168.178.66"

class HassioEcoFlowClient:
    __disconnected = None
    __extra_connected = False

    def __init__(self):
        self.tcp = RxTcpAutoConnection(CONF_EF, ef.PORT)
        self.product: int = list(ef.PRODUCTS.keys())[list(ef.PRODUCTS.values()).index(CONF_PRODUCT)]
        self.diagnostics = dict[str, dict[str, Any]]()

        self.device_info_main={}
        self.device_info_main["manufacturer"] = "EcoFlow"

        self.received = self.tcp.received.pipe(
            receive.merge_packet(),
            ops.map(receive.decode_packet),
            ops.share(),
        )
        self.pd = self.received.pipe(
            ops.filter(receive.is_pd),
            ops.map(lambda x: receive.parse_pd(x[3], self.product)),
            ops.multicast(subject=ReplaySubject(1, DISCONNECT_TIME)),
            ops.ref_count(),
        )
        self.ems = self.received.pipe(
            ops.filter(receive.is_ems),
            ops.map(lambda x: receive.parse_ems(x[3], self.product)),
            ops.multicast(subject=ReplaySubject(1, DISCONNECT_TIME)),
            ops.ref_count(),
        )
        self.inverter = self.received.pipe(
            ops.filter(receive.is_inverter),
            ops.map(lambda x: receive.parse_inverter(x[3], self.product)),
            ops.multicast(subject=ReplaySubject(1, DISCONNECT_TIME)),
            ops.ref_count(),
        )
        self.mppt = self.received.pipe(
            ops.filter(receive.is_mppt),
            ops.map(lambda x: receive.parse_mppt(x[3], self.product)),
            ops.multicast(subject=ReplaySubject(1, DISCONNECT_TIME)),
            ops.ref_count(),
        )
        self.bms = self.received.pipe(
            ops.filter(receive.is_bms),
            ops.map(lambda x: receive.parse_bms(x[3], self.product)),
            ops.multicast(subject=ReplaySubject(1, DISCONNECT_TIME)),
            ops.ref_count(),
        )

        self.dc_in_current_config = self.received.pipe(
            ops.filter(receive.is_dc_in_current_config),
            ops.map(lambda x: receive.parse_dc_in_current_config(x[3])),
        )
        self.dc_in_type = self.received.pipe(
            ops.filter(receive.is_dc_in_type),
            ops.map(lambda x: receive.parse_dc_in_type(x[3])),
        )
        self.fan_auto = self.received.pipe(
            ops.filter(receive.is_fan_auto),
            ops.map(lambda x: receive.parse_fan_auto(x[3])),
        )
        self.lcd_timeout = self.received.pipe(
            ops.filter(receive.is_lcd_timeout),
            ops.map(lambda x: receive.parse_lcd_timeout(x[3])),
        )

        self.disconnected = Subject[Optional[int]]()

        def _disconnected(*args):
            self.__disconnected = None
            self.tcp.reconnect()
            self.diagnostics.clear()
            self.disconnected.on_next(None)
            if self.__extra_connected:
                self.__extra_connected = False

        def reset_timer(*args):
            if self.__disconnected:
                self.__disconnected()

        def end_timer(ex=None):
            self.disconnected.on_next(None)
            if ex:
                self.disconnected.on_error(ex)
            else:
                self.disconnected.on_completed()
        self.received.subscribe(reset_timer, end_timer, end_timer)

        def pd_updated(data: dict[str, Any]):
            self.diagnostics["pd"] = data
            self.device_info_main["model"] = ef.get_model_name(
                self.product, data["model"])
            if self.__extra_connected != ef.has_extra(self.product, data.get("model", None)):
                self.__extra_connected = not self.__extra_connected
                if not self.__extra_connected:
                    self.disconnected.on_next(1)
        self.pd.subscribe(pd_updated)

        def bms_updated(data: tuple[int, dict[str, Any]]):
            if "bms" not in self.diagnostics:
                self.diagnostics["bms"] = dict[str, Any]()
            self.diagnostics["bms"][data[0]] = data[1]
        self.bms.subscribe(bms_updated)

        def ems_updated(data: dict[str, Any]):
            self.diagnostics["ems"] = data
        self.ems.subscribe(ems_updated)

        def inverter_updated(data: dict[str, Any]):
            self.diagnostics["inverter"] = data
        self.inverter.subscribe(inverter_updated)

        def mppt_updated(data: dict[str, Any]):
            self.diagnostics["mppt"] = data
        self.mppt.subscribe(mppt_updated)

    async def close(self):
        self.tcp.close()
        await self.tcp.wait_closed()

async def main():
  client =  HassioEcoFlowClient()
  #while "pd" not in client.diagnostics:
  #  await asyncio.sleep(0)
  await asyncio.sleep(5)
  print(client.diagnostics)
  await client.close()

asyncio.run(main())

