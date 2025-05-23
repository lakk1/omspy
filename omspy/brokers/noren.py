from omspy.base import Broker, pre, post
from typing import Optional, List, Dict, Union, Set
import pendulum
import pyotp
import logging
from NorenRestApiPy.NorenApi import NorenApi


class BaseNoren(NorenApi):
    def __init__(self, host: str, websocket: str):
        super(BaseNoren, self).__init__(host=host, websocket=websocket)


class Noren(Broker):
    def __init__(
        self,
        user_id: str,
        password: str,
        totp: str,
        vendor_code: str,
        app_key: str,
        imei: str,
        *args,
        **kwargs,
    ):
        self._user_id = user_id
        self._password = password
        self._totp = totp
        self._vendor_code = vendor_code
        self._app_key = app_key
        self._imei = imei
        self._host = kwargs.get("host", "https://star.prostocks.com/NorenWClientTP")
        self._websocket = kwargs.get("websocket", "wss://star.prostocks.com/NorenWS/")
        self.noren = None
        super(Noren, self).__init__()

    @property
    def attribs_to_copy_modify(self) -> set:
        return {"symbol", "exchange"}

    def login(self):
        return self.noren.login(
            userid=self._user_id,
            password=self._password,
            twoFA=pyotp.TOTP(self._totp).now(),
            vendor_code=self._vendor_code,
            api_secret=self._app_key,
            imei=self._imei,
        )

    def authenticate(self) -> Union[Dict, None]:
        self.noren = BaseNoren(self._host, self._websocket)
        return self.login()

    def _convert_symbol(self, symbol: str, exchange: str = "NSE") -> str:
        """
        Convert raw symbol to noren
        """
        if exchange == "NSE":
            if symbol.upper().endswith("-EQ"):
                return symbol
            else:
                return f"{symbol}-EQ"
        else:
            return symbol

    def get_order_type(self, order_type: str) -> str:
        """
        Convert a generic order type to this specific
        broker's order type string
        returns MKT if the order_type is not matching
        """
        order_types = dict(
            LIMIT="LMT",
            MARKET="MKT",
            SL="SL-LMT",
            SLM="SL-MKT",
            SLL="SL-LMT",
            LMT="LMT",
            MKT="MKT",
        )
        order_types["SL-M"] = "SL-MKT"
        order_types["SL-L"] = "SL-LMT"
        return order_types.get(order_type.upper(), "MKT")

    @pre
    def order_place(self, **kwargs) -> Union[str, None]:
        side = kwargs.pop("buy_or_sell")
        order_type = kwargs.pop("price_type", "MKT")
        exchange = kwargs.pop("exchange", "NSE")
        symbol = kwargs.pop("tradingsymbol")
        symbol = self._convert_symbol(symbol, exchange=exchange)
        if order_type:
            order_type = self.get_order_type(order_type)
        if side:
            side = side.upper()[0]
        if symbol:
            symbol = symbol.upper()
        order_args = dict(
            tradingsymbol=symbol,
            buy_or_sell=side,
            price_type=order_type,
            exchange=exchange,
            retention="DAY",
            product_type="I",
            discloseqty=0,
        )
        order_args.update(kwargs)
        response = self.noren.place_order(**order_args)
        return response.get("norenordno")

    @pre
    def order_modify(self, **kwargs) -> Union[str, None]:
        """
        Modify an existing order
        """
        symbol = kwargs.pop("tradingsymbol")
        order_id = kwargs.pop("order_id", None)
        order_type = kwargs.pop("order_type", "MKT")
        if "discloseqty" in kwargs:
            kwargs.pop("discloseqty")
        if order_type:
            order_type = self.get_order_type(order_type)
        if symbol:
            symbol = self._convert_symbol(symbol).upper()
        order_args = dict(
            orderno=order_id,
            newprice_type=order_type,
            exchange="NSE",
            tradingsymbol=symbol,
        )
        order_args.update(kwargs)
        return self.noren.modify_order(**order_args)

    def order_cancel(self, order_id: str) -> Union[Dict, None]:
        """
        Cancel an existing order
        """
        return self.noren.cancel_order(orderno=order_id)

    @property
    @post
    def orders(self) -> List[Dict]:
        orderbook = self.noren.get_order_book()
        if not orderbook:
            return []

        order_list = []
        float_cols = ["avgprc", "prc", "rprc", "trgprc"]
        int_cols = ["fillshares", "qty"]
        for order in orderbook:
            try:
                for int_col in int_cols:
                    order[int_col] = int(order.get(int_col, 0))
                for float_col in float_cols:
                    order[float_col] = float(order.get(float_col, 0))
                ts = order.get("exch_tm")
                if ts:
                    # Timestamp converted to str to facilitate loading into pandas dataframe
                    order["exchange_timestamp"] = str(
                        pendulum.from_format(
                            ts, fmt="DD-MM-YYYY HH:mm:ss", tz="Asia/Kolkata"
                        )
                    )
                else:
                    order["exchange_timestamp"] = None
                ts2 = order["norentm"]
                order["broker_timestamp"] = str(
                    pendulum.from_format(
                        ts2, fmt="HH:mm:ss DD-MM-YYYY", tz="Asia/Kolkata"
                    )
                )
            except Exception as e:
                logging.error(e)
            order_list.append(order)
        return order_list

    @property
    @post
    def positions(self) -> List[Dict]:
        positionbook = self.noren.get_positions()
        if len(positionbook) == 0:
            return positionbook

        position_list = []
        int_cols = [
            "netqty",
            "daybuyqty",
            "daysellqty",
            "cfbuyqty",
            "cfsellqty",
            "openbuyqty",
            "opensellqty",
        ]
        float_cols = [
            "daybuyamt",
            "daysellamt",
            "lp",
            "rpnl",
            "dayavgprc",
            "daybuyavgprc",
            "daysellavgprc",
            "urmtom",
        ]
        for position in positionbook:
            try:
                for int_col in int_cols:
                    position[int_col] = int(position.get(int_col, 0))
                for float_col in float_cols:
                    position[float_col] = float(position.get(float_col, 0))
            except Exception as e:
                logging.error(e)
            position_list.append(position)
        return position_list

    @property
    @post
    def trades(self) -> List[Dict]:
        tradebook = self.noren.get_trade_book()
        if len(tradebook) == 0:
            return tradebook

        trade_list = []
        int_cols = ["flqty", "qty", "fillshares"]
        float_cols = ["prc", "flprc"]
        for trade in tradebook:
            try:
                for int_col in int_cols:
                    trade[int_col] = int(trade.get(int_col, 0))
                for float_col in float_cols:
                    trade[float_col] = float(trade.get(float_col, 0))
            except Exception as e:
                logging.error(e)
            trade_list.append(trade)
        return trade_list
