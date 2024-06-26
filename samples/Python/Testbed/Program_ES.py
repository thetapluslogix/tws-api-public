"""
Copyright (C) 2019 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.
"""

import argparse
import datetime
import collections
import inspect

import logging
from math import floor
import time
import os.path

from ibapi import wrapper
from ibapi.client import EClient
from ibapi.utils import longMaxString
from ibapi.utils import iswrapper

# types
from ibapi.common import * # @UnusedWildImport
from ibapi.order_condition import * # @UnusedWildImport
from ibapi.contract import * # @UnusedWildImport
from ibapi.order import * # @UnusedWildImport
from ibapi.order_state import * # @UnusedWildImport
from ibapi.execution import Execution
from ibapi.execution import ExecutionFilter
from ibapi.commission_report import CommissionReport
from ibapi.ticktype import * # @UnusedWildImport
from ibapi.tag_value import TagValue

from ibapi.account_summary_tags import *

from ContractSamples import ContractSamples
from OrderSamples import OrderSamples
from AvailableAlgoParams import AvailableAlgoParams
from ScannerSubscriptionSamples import ScannerSubscriptionSamples
from FaAllocationSamples import FaAllocationSamples
from ibapi.scanner import ScanData

import threading
import queue

def SetupLogger():
    if not os.path.exists("log"):
        os.makedirs("log")

    time.strftime("pyibapi.%Y%m%d_%H%M%S.log")

    recfmt = '(%(threadName)s) %(asctime)s.%(msecs)03d %(levelname)s %(filename)s:%(lineno)d %(message)s'

    timefmt = '%y%m%d_%H:%M:%S'

    # logging.basicConfig( level=logging.DEBUG,
    #                    format=recfmt, datefmt=timefmt)
    logging.basicConfig(filename=time.strftime("log/pyibapi.%y%m%d_%H%M%S.log"),
                        filemode="w",
                        level=logging.INFO,
                        format=recfmt, datefmt=timefmt)
    logger = logging.getLogger()
    console = logging.StreamHandler()
    console.setLevel(logging.ERROR)
    logger.addHandler(console)


def printWhenExecuting(fn):
    def fn2(self):
        print("   doing", fn.__name__)
        fn(self)
        print("   done w/", fn.__name__)

    return fn2

def printinstance(inst:Object):
    attrs = vars(inst)
    #print(', '.join('{}:{}'.format(key, decimalMaxString(value) if type(value) is Decimal else value) for key, value in attrs.items()))
    print(', '.join('{}:{}'.format(key, decimalMaxString(value) if type(value) is Decimal else
                                   floatMaxString(value) if type(value) is float else
                                   intMaxString(value) if type(value) is int else  
                                   value) for key, value in attrs.items()))

class Activity(Object):
    def __init__(self, reqMsgId, ansMsgId, ansEndMsgId, reqId):
        self.reqMsdId = reqMsgId
        self.ansMsgId = ansMsgId
        self.ansEndMsgId = ansEndMsgId
        self.reqId = reqId


class RequestMgr(Object):
    def __init__(self):
        # I will keep this simple even if slower for now: only one list of
        # requests finding will be done by linear search
        self.requests = []

    def addReq(self, req):
        self.requests.append(req)

    def receivedMsg(self, msg):
        pass


# ! [socket_declare]
class TestClient(EClient):
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)
        # ! [socket_declare]

        # how many times a method is called to see test coverage
        self.clntMeth2callCount = collections.defaultdict(int)
        self.clntMeth2reqIdIdx = collections.defaultdict(lambda: -1)
        self.reqId2nReq = collections.defaultdict(int)
        self.setupDetectReqId()

    def countReqId(self, methName, fn):
        def countReqId_(*args, **kwargs):
            self.clntMeth2callCount[methName] += 1
            idx = self.clntMeth2reqIdIdx[methName]
            if idx >= 0:
                sign = -1 if 'cancel' in methName else 1
                self.reqId2nReq[sign * args[idx]] += 1
            return fn(*args, **kwargs)

        return countReqId_

    def setupDetectReqId(self):

        methods = inspect.getmembers(EClient, inspect.isfunction)
        for (methName, meth) in methods:
            if methName != "send_msg":
                # don't screw up the nice automated logging in the send_msg()
                self.clntMeth2callCount[methName] = 0
                # logging.debug("meth %s", name)
                sig = inspect.signature(meth)
                for (idx, pnameNparam) in enumerate(sig.parameters.items()):
                    (paramName, param) = pnameNparam # @UnusedVariable
                    if paramName == "reqId":
                        self.clntMeth2reqIdIdx[methName] = idx

                setattr(TestClient, methName, self.countReqId(methName, meth))

                # print("TestClient.clntMeth2reqIdIdx", self.clntMeth2reqIdIdx)


# ! [ewrapperimpl]
class TestWrapper(wrapper.EWrapper):
    # ! [ewrapperimpl]
    def __init__(self):
        wrapper.EWrapper.__init__(self)

        self.wrapMeth2callCount = collections.defaultdict(int)
        self.wrapMeth2reqIdIdx = collections.defaultdict(lambda: -1)
        self.reqId2nAns = collections.defaultdict(int)
        self.setupDetectWrapperReqId()

    # TODO: see how to factor this out !!

    def countWrapReqId(self, methName, fn):
        def countWrapReqId_(*args, **kwargs):
            self.wrapMeth2callCount[methName] += 1
            idx = self.wrapMeth2reqIdIdx[methName]
            if idx >= 0:
                self.reqId2nAns[args[idx]] += 1
            return fn(*args, **kwargs)

        return countWrapReqId_

    def setupDetectWrapperReqId(self):

        methods = inspect.getmembers(wrapper.EWrapper, inspect.isfunction)
        for (methName, meth) in methods:
            self.wrapMeth2callCount[methName] = 0
            # logging.debug("meth %s", name)
            sig = inspect.signature(meth)
            for (idx, pnameNparam) in enumerate(sig.parameters.items()):
                (paramName, param) = pnameNparam # @UnusedVariable
                # we want to count the errors as 'error' not 'answer'
                if 'error' not in methName and paramName == "reqId":
                    self.wrapMeth2reqIdIdx[methName] = idx

            setattr(TestWrapper, methName, self.countWrapReqId(methName, meth))

            # print("TestClient.wrapMeth2reqIdIdx", self.wrapMeth2reqIdIdx)


# this is here for documentation generation
"""
#! [ereader]
        # You don't need to run this in your code!
        self.reader = reader.EReader(self.conn, self.msg_queue)
        self.reader.start()   # start thread
#! [ereader]
"""
class spxwPrice(Object):
    def __init__(self, contract, tickType, price, attrib):
        self.contract = contract
        self.price = price
        self.tickType = tickType
        self.attrib = attrib

    def __str__(self):
        return "contract:%s tickType:%s price:%s attrib:%s" % (self.contract, self.tickType, self.price, self.attrib)
    
class spxwPosition(Object):
    def __init__(self, account, contract, position, avgCost):
        self.account = account
        self.contract = contract
        self.position = position
        self.avgCost = avgCost

    def __str__(self):
        return "account:%s contract:%s position:%s avgCost:%s" % (self.account, self.contract, self.position, self.avgCost)

# ! [socket_init]
class TestApp(TestWrapper, TestClient):
    def __init__(self):
        TestWrapper.__init__(self)
        TestClient.__init__(self, wrapper=self)
        self.ESDynamicStraddleStrategy = ESDynamicStraddleStrategy(self)
        # ! [socket_init]
        self.nKeybInt = 0
        self.started = False
        self.nextValidOrderId = None
        self.permId2ord = {}
        self.reqId2nErr = collections.defaultdict(int)
        self.globalCancelOnly = False
        self.simplePlaceOid = None
        self.spxwPositions = []
        self.spxwPositions_ = []
        self.tradingDay = None
        self.nextTradingDay = None
        self.actionableStrike = None
        self.MktDataRequest = {} #key is reqId, value is contract
        #get the current trading day
        #if time is after 13:00 PDT but before midnight, then the trading day is the next day, else it is today
        self.tradingDay = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
        if datetime.datetime.now(datetime.timezone.utc).hour >= 20:
            self.tradingDay = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).strftime('%Y%m%d')
        #if tradingDay is Monday through Thursday, then the next trading day is the next day, else it is the next Monday
        if datetime.datetime.strptime(self.tradingDay, '%Y%m%d').weekday() == 3:
            self.nextTradingDay = (datetime.datetime.strptime(self.tradingDay, '%Y%m%d') + datetime.timedelta(days=3)).strftime('%Y%m%d')
        elif datetime.datetime.strptime(self.tradingDay, '%Y%m%d').weekday() == 4:
            self.nextTradingDay = (datetime.datetime.strptime(self.tradingDay, '%Y%m%d') + datetime.timedelta(days=2)).strftime('%Y%m%d')
        elif datetime.datetime.strptime(self.tradingDay, '%Y%m%d').weekday() == 5:
            self.nextTradingDay = (datetime.datetime.strptime(self.tradingDay, '%Y%m%d') + datetime.timedelta(days=1)).strftime('%Y%m%d')

        self.spxwPrices = [] #value is array of spxwPrice
        
        self.message_from_ib_queue = queue.Queue()



    def dumpTestCoverageSituation(self):
        for clntMeth in sorted(self.clntMeth2callCount.keys()):
            logging.debug("ClntMeth: %-30s %6d" % (clntMeth,
                                                   self.clntMeth2callCount[clntMeth]))

        for wrapMeth in sorted(self.wrapMeth2callCount.keys()):
            logging.debug("WrapMeth: %-30s %6d" % (wrapMeth,
                                                   self.wrapMeth2callCount[wrapMeth]))

    def dumpReqAnsErrSituation(self):
        logging.debug("%s\t%s\t%s\t%s" % ("ReqId", "#Req", "#Ans", "#Err"))
        for reqId in sorted(self.reqId2nReq.keys()):
            nReq = self.reqId2nReq.get(reqId, 0)
            nAns = self.reqId2nAns.get(reqId, 0)
            nErr = self.reqId2nErr.get(reqId, 0)
            logging.debug("%d\t%d\t%s\t%d" % (reqId, nReq, nAns, nErr))

    @iswrapper
    # ! [connectack]
    def connectAck(self):
        if self.asynchronous:
            self.startApi()

    # ! [connectack]

    @iswrapper
    # ! [nextvalidid]
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)

        logging.debug("setting nextValidOrderId: %d", orderId)
        self.nextValidOrderId = orderId
        print("NextValidId:", orderId)
    # ! [nextvalidid]

        # we can start now
        if hasattr(self, 'account'):
            self.start()

    def start(self):
        if self.started:
            return

        self.started = True

        if self.globalCancelOnly:
            print("Executing GlobalCancel only")
            #write ESDynamicStraddleStrategy log file
            self.ESDynamicStraddleStrategy.log_file_handle.write("Executing GlobalCancel only\n")
            self.reqGlobalCancel()
        #else:
        if True:
            print("Executing requests")
            #write ESDynamicStraddleStrategy log file
            self.ESDynamicStraddleStrategy.log_file_handle.write("Executing requests\n")

            #self.reqGlobalCancel()
            #self.marketDataTypeOperations()
            #self.accountOperations_req()
            #self.tickDataOperations_req()
            #self.tickOptionComputations_req()
            #self.marketDepthOperations_req()
            #self.realTimeBarsOperations_req()
            #self.historicalDataOperations_req()
            #self.optionsOperations_req()
            #self.marketScannersOperations_req()
            #self.fundamentalsOperations_req()
            #self.bulletinsOperations_req()

            #get a new reqId
            reqId = self.nextOrderId()
            self.ESDynamicStraddleStrategy.subscribeToMarketData(reqId,self)
            #subscribe for position updates
            self.ESDynamicStraddleStrategy.subscribePositions(self)

            #self.contractOperations_SPXW()
            
            #self.newsOperations_req()
            #self.miscelaneousOperations()
            #self.linkingOperations()
            #self.financialAdvisorOperations()
            #self.orderOperations_req()
            #self.orderOperations_cancel()
            #self.rerouteCFDOperations()
            #self.marketRuleOperations()
            #self.pnlOperations_req()
            #self.histogramOperations_req()
            #self.continuousFuturesOperations_req()
            #self.historicalTicksOperations()
            #self.tickByTickOperations_req()
            #self.whatIfOrderOperations()
            #self.wshCalendarOperations()
            
            print("Executing requests ... finished")

    def keyboardInterrupt(self):
        self.nKeybInt += 1
        if self.nKeybInt == 1:
            self.stop()
        else:
            print("Finishing test")
            self.done = True

    def stop(self):
        print("Executing cancels")
        #self.orderOperations_cancel()
        #self.accountOperations_cancel()
        #self.tickDataOperations_cancel()
        #self.tickOptionComputations_cancel()
        #self.marketDepthOperations_cancel()
        #self.realTimeBarsOperations_cancel()
        #self.historicalDataOperations_cancel()
        #self.optionsOperations_cancel()
        #self.marketScanners_cancel()
        #self.fundamentalsOperations_cancel()
        #self.bulletinsOperations_cancel()
        #self.newsOperations_cancel()
        #self.pnlOperations_cancel()
        #self.histogramOperations_cancel()
        #self.continuousFuturesOperations_cancel()
        #self.tickByTickOperations_cancel()
        print("Executing cancels ... finished")

    def nextOrderId(self):
        oid = self.nextValidOrderId
        self.nextValidOrderId += 1
        return oid

    @iswrapper
    # ! [error]
    def error(self, reqId: TickerId, errorCode: int, errorString: str, advancedOrderRejectJson = ""):
        super().error(reqId, errorCode, errorString, advancedOrderRejectJson)
        if advancedOrderRejectJson:
            print("Error. Id:", reqId, "Code:", errorCode, "Msg:", errorString, "AdvancedOrderRejectJson:", advancedOrderRejectJson)
            #write ESDynamicStraddleStrategy log file
            self.ESDynamicStraddleStrategy.log_file_handle.write("Error. Id: %s Code: %s Msg: %s AdvancedOrderRejectJson: %s\n" % (reqId, errorCode, errorString, advancedOrderRejectJson))
        else:
            print("Error. Id:", reqId, "Code:", errorCode, "Msg:", errorString)
            #write ESDynamicStraddleStrategy log file
            self.ESDynamicStraddleStrategy.log_file_handle.write("Error. Id: %s Code: %s Msg: %s\n" % (reqId, errorCode, errorString))

    # ! [error] self.reqId2nErr[reqId] += 1


    @iswrapper
    def winError(self, text: str, lastError: int):
        super().winError(text, lastError)

    @iswrapper
    # ! [openorder]
    def openOrder(self, orderId: OrderId, contract: Contract, order: Order,
                  orderState: OrderState):
        super().openOrder(orderId, contract, order, orderState)
        print("OpenOrder. PermId:", intMaxString(order.permId), "ClientId:", intMaxString(order.clientId), " OrderId:", intMaxString(orderId), 
            "Account:", order.account, "Symbol:", contract.symbol, "SecType:", contract.secType,
            "Exchange:", contract.exchange, "Action:", order.action, "OrderType:", order.orderType,
            "TotalQty:", decimalMaxString(order.totalQuantity), "CashQty:", floatMaxString(order.cashQty), 
            "LmtPrice:", floatMaxString(order.lmtPrice), "AuxPrice:", floatMaxString(order.auxPrice), "Status:", orderState.status,
            "MinTradeQty:", intMaxString(order.minTradeQty), "MinCompeteSize:", intMaxString(order.minCompeteSize),
            "competeAgainstBestOffset:", "UpToMid" if order.competeAgainstBestOffset == COMPETE_AGAINST_BEST_OFFSET_UP_TO_MID else floatMaxString(order.competeAgainstBestOffset),
            "MidOffsetAtWhole:", floatMaxString(order.midOffsetAtWhole),"MidOffsetAtHalf:" ,floatMaxString(order.midOffsetAtHalf))
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("OpenOrder. PermId: %s ClientId: %s OrderId: %s Account: %s Symbol: %s SecType: %s Exchange: %s Action: %s OrderType: %s TotalQty: %s CashQty: %s LmtPrice: %s AuxPrice: %s Status: %s MinTradeQty: %s MinCompeteSize: %s competeAgainstBestOffset: %s MidOffsetAtWhole: %s MidOffsetAtHalf: %s\n" % (intMaxString(order.permId), intMaxString(order.clientId), intMaxString(orderId), order.account, contract.symbol, contract.secType, contract.exchange, order.action, order.orderType, decimalMaxString(order.totalQuantity), floatMaxString(order.cashQty), floatMaxString(order.lmtPrice), floatMaxString(order.auxPrice), orderState.status, intMaxString(order.minTradeQty), intMaxString(order.minCompeteSize), "UpToMid" if order.competeAgainstBestOffset == COMPETE_AGAINST_BEST_OFFSET_UP_TO_MID else floatMaxString(order.competeAgainstBestOffset), floatMaxString(order.midOffsetAtWhole), floatMaxString(order.midOffsetAtHalf)))
        self.message_from_ib_queue.put(("open_order", orderId, contract, order, orderState))
        
        #order.contract = contract
        self.permId2ord[order.permId] = order

    # ! [openorder]

    @iswrapper
    # ! [openorderend]
    def openOrderEnd(self):
        super().openOrderEnd()
        print("OpenOrderEnd")
        #self.ESDynamicStraddleStrategy.log_file_handle.write("OpenOrderEnd\n")
        #self.ESDynamicStraddleStrategy.call_stplmt_profit_open_orders_tuples.clear()
        ##self.ESDynamicStraddleStrategy.put_stplmt_profit_open_orders_tuples.clear()
        #elf.ESDynamicStraddleStrategy.call_stplmt_open_orders_tuples.clear()
        #elf.ESDynamicStraddleStrategy.put_stplmt_open_orders_tuples.clear()
        #self.ESDynamicStraddleStrategy.call_bracket_order_maintenance_on_hold = False
        #self.ESDynamicStraddleStrategy.put_bracket_order_maintenance_on_hold = False
        
        logging.debug("Received %d openOrders", len(self.permId2ord))
    # ! [openorderend]

    @iswrapper
    # ! [orderstatus]
    def orderStatus(self, orderId: OrderId, status: str, filled: Decimal,
                    remaining: Decimal, avgFillPrice: float, permId: int,
                    parentId: int, lastFillPrice: float, clientId: int,
                    whyHeld: str, mktCapPrice: float):
        super().orderStatus(orderId, status, filled, remaining,
                            avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        print("OrderStatus. Id:", orderId, "Status:", status, "Filled:", decimalMaxString(filled),
              "Remaining:", decimalMaxString(remaining), "AvgFillPrice:", floatMaxString(avgFillPrice),
              "PermId:", intMaxString(permId), "ParentId:", intMaxString(parentId), "LastFillPrice:",
              floatMaxString(lastFillPrice), "ClientId:", intMaxString(clientId), "WhyHeld:",
              whyHeld, "MktCapPrice:", floatMaxString(mktCapPrice))
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("OrderStatus. Id: %s Status: %s Filled: %s Remaining: %s AvgFillPrice: %s PermId: %s ParentId: %s LastFillPrice: %s ClientId: %s WhyHeld: %s MktCapPrice: %s\n" % (orderId, status, decimalMaxString(filled), decimalMaxString(remaining), floatMaxString(avgFillPrice), intMaxString(permId), intMaxString(parentId), floatMaxString(lastFillPrice), intMaxString(clientId), whyHeld, floatMaxString(mktCapPrice)))
    # ! [orderstatus]


    @printWhenExecuting
    def accountOperations_req(self):
        # Requesting managed accounts
        # ! [reqmanagedaccts]
        self.reqManagedAccts()
        # ! [reqmanagedaccts]

        # Requesting family codes
        # ! [reqfamilycodes]
        self.reqFamilyCodes()
        # ! [reqfamilycodes]

        # Requesting accounts' summary
        # ! [reqaaccountsummary]
        self.reqAccountSummary(9001, "All", AccountSummaryTags.AllTags)
        # ! [reqaaccountsummary]

        # ! [reqaaccountsummaryledger]
        self.reqAccountSummary(9002, "All", "$LEDGER")
        # ! [reqaaccountsummaryledger]

        # ! [reqaaccountsummaryledgercurrency]
        self.reqAccountSummary(9003, "All", "$LEDGER:EUR")
        # ! [reqaaccountsummaryledgercurrency]

        # ! [reqaaccountsummaryledgerall]
        self.reqAccountSummary(9004, "All", "$LEDGER:ALL")
        # ! [reqaaccountsummaryledgerall]

        # Subscribing to an account's information. Only one at a time!
        # ! [reqaaccountupdates]
        self.reqAccountUpdates(True, self.account)
        # ! [reqaaccountupdates]

        # ! [reqaaccountupdatesmulti]
        self.reqAccountUpdatesMulti(9005, self.account, "", True)
        # ! [reqaaccountupdatesmulti]

        # Requesting all accounts' positions.
        # ! [reqpositions]
        self.reqPositions()
        # ! [reqpositions]

        # ! [reqpositionsmulti]
        self.reqPositionsMulti(9006, self.account, "")
        # ! [reqpositionsmulti]

        # ! [requserinfo]
        self.reqUserInfo(0)
        # ! [requserinfo]

    @printWhenExecuting
    def accountOperations_cancel(self):
        # ! [cancelaaccountsummary]
        self.cancelAccountSummary(9001)
        self.cancelAccountSummary(9002)
        self.cancelAccountSummary(9003)
        self.cancelAccountSummary(9004)
        # ! [cancelaaccountsummary]

        # ! [cancelaaccountupdates]
        self.reqAccountUpdates(False, self.account)
        # ! [cancelaaccountupdates]

        # ! [cancelaaccountupdatesmulti]
        self.cancelAccountUpdatesMulti(9005)
        # ! [cancelaaccountupdatesmulti]

        # ! [cancelpositions]
        self.cancelPositions()
        # ! [cancelpositions]

        # ! [cancelpositionsmulti]
        self.cancelPositionsMulti(9006)
        # ! [cancelpositionsmulti]

    def pnlOperations_req(self):
        # ! [reqpnl]
        self.reqPnL(17001, "DU111519", "")
        # ! [reqpnl]

        # ! [reqpnlsingle]
        self.reqPnLSingle(17002, "DU111519", "", 8314);
        # ! [reqpnlsingle]

    def pnlOperations_cancel(self):
        # ! [cancelpnl]
        self.cancelPnL(17001)
        # ! [cancelpnl]

        # ! [cancelpnlsingle]
        self.cancelPnLSingle(17002);
        # ! [cancelpnlsingle]

    def histogramOperations_req(self):
        # ! [reqhistogramdata]
        self.reqHistogramData(4002, ContractSamples.USStockAtSmart(), False, "3 days");
        # ! [reqhistogramdata]

    def histogramOperations_cancel(self):
        # ! [cancelhistogramdata]
        self.cancelHistogramData(4002);
        # ! [cancelhistogramdata]

    def continuousFuturesOperations_req(self):
        # ! [reqcontractdetailscontfut]
        self.reqContractDetails(18001, ContractSamples.ContFut())
        # ! [reqcontractdetailscontfut]

        # ! [reqhistoricaldatacontfut]
        timeStr = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H:%M:%S')
        self.reqHistoricalData(18002, ContractSamples.ContFut(), timeStr, "1 Y", "1 month", "TRADES", 0, 1, False, []);
        # ! [reqhistoricaldatacontfut]

    def continuousFuturesOperations_cancel(self):
        # ! [cancelhistoricaldatacontfut]
        self.cancelHistoricalData(18002);
        # ! [cancelhistoricaldatacontfut]

    @iswrapper
    # ! [managedaccounts]
    def managedAccounts(self, accountsList: str):
        super().managedAccounts(accountsList)
        print("Account list:", accountsList)
        # ! [managedaccounts]
        #check if accountsList has more than one account by checking if it has a comma
        has_comma = accountsList.find(",")
        if has_comma != -1:
            self.account = accountsList.split(",")[1]
        else:
            self.account = accountsList
        
        if self.nextValidOrderId is not None:
            self.start()

    @iswrapper
    # ! [accountsummary]
    def accountSummary(self, reqId: int, account: str, tag: str, value: str,
                       currency: str):
        super().accountSummary(reqId, account, tag, value, currency)
        print("AccountSummary. ReqId:", reqId, "Account:", account,
              "Tag: ", tag, "Value:", value, "Currency:", currency)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("AccountSummary. ReqId: %s Account: %s Tag: %s Value: %s Currency: %s\n" % (reqId, account, tag, value, currency))
    # ! [accountsummary]

    @iswrapper
    # ! [accountsummaryend]
    def accountSummaryEnd(self, reqId: int):
        super().accountSummaryEnd(reqId)
        print("AccountSummaryEnd. ReqId:", reqId)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("AccountSummaryEnd. ReqId: %s\n" % reqId)
    # ! [accountsummaryend]

    @iswrapper
    # ! [updateaccountvalue]
    def updateAccountValue(self, key: str, val: str, currency: str,
                           accountName: str):
        super().updateAccountValue(key, val, currency, accountName)
        print("UpdateAccountValue. Key:", key, "Value:", val,
              "Currency:", currency, "AccountName:", accountName)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("UpdateAccountValue. Key: %s Value: %s Currency: %s AccountName: %s\n" % (key, val, currency, accountName))
    # ! [updateaccountvalue]

    @iswrapper
    # ! [updateportfolio]
    def updatePortfolio(self, contract: Contract, position: Decimal,
                        marketPrice: float, marketValue: float,
                        averageCost: float, unrealizedPNL: float,
                        realizedPNL: float, accountName: str):
        super().updatePortfolio(contract, position, marketPrice, marketValue,
                                averageCost, unrealizedPNL, realizedPNL, accountName)
        print("UpdatePortfolio.", "Symbol:", contract.symbol, "SecType:", contract.secType, "Exchange:",
              contract.exchange, "Position:", decimalMaxString(position), "MarketPrice:", floatMaxString(marketPrice),
              "MarketValue:", floatMaxString(marketValue), "AverageCost:", floatMaxString(averageCost),
              "UnrealizedPNL:", floatMaxString(unrealizedPNL), "RealizedPNL:", floatMaxString(realizedPNL),
              "AccountName:", accountName)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("UpdatePortfolio. Symbol: %s SecType: %s Exchange: %s Position: %s MarketPrice: %s MarketValue: %s AverageCost: %s UnrealizedPNL: %s RealizedPNL: %s AccountName: %s\n" % (contract.symbol, contract.secType, contract.exchange, decimalMaxString(position), floatMaxString(marketPrice), floatMaxString(marketValue), floatMaxString(averageCost), floatMaxString(unrealizedPNL), floatMaxString(realizedPNL), accountName))
    # ! [updateportfolio]

    @iswrapper
    # ! [updateaccounttime]
    def updateAccountTime(self, timeStamp: str):
        super().updateAccountTime(timeStamp)
        print("UpdateAccountTime. Time:", timeStamp)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("UpdateAccountTime. Time: %s\n" % timeStamp)
    # ! [updateaccounttime]

    @iswrapper
    # ! [accountdownloadend]
    def accountDownloadEnd(self, accountName: str):
        super().accountDownloadEnd(accountName)
        print("AccountDownloadEnd. Account:", accountName)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("AccountDownloadEnd. Account: %s\n" % accountName)
    # ! [accountdownloadend]

    @iswrapper
    # ! [position]
    def position(self, account: str, contract: Contract, position: Decimal,
                 avgCost: float):
        super().position(account, contract, position, avgCost)
        print("Position.", "Account:", account, "Symbol:", contract.symbol, "SecType:",
              contract.secType, "Currency:", contract.currency,
              "Position:", decimalMaxString(position), "Avg cost:", floatMaxString(avgCost))
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("Position. Account: %s Symbol: %s SecType: %s Currency: %s Position: %s Avg cost: %s\n" % (account, contract.symbol, contract.secType, contract.currency, decimalMaxString(position), floatMaxString(avgCost)))
        self.message_from_ib_queue.put(("position", account, contract, position, avgCost))
         # ! [position]

    @iswrapper
    # ! [positionend]
    def positionEnd(self):
        super().positionEnd()
        print("PositionEnd")
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("PositionEnd\n")
    # ! [positionend]

    @iswrapper
    # ! [positionmulti]
    def positionMulti(self, reqId: int, account: str, modelCode: str,
                      contract: Contract, pos: Decimal, avgCost: float):
        super().positionMulti(reqId, account, modelCode, contract, pos, avgCost)
        if contract.secType == 'OPT' and contract.symbol == 'SPX':
            if contract.lastTradeDateOrContractMonth == self.tradingDay or contract.lastTradeDateOrContractMonth == self.nextTradingDay:
                self.spxwPositions_.append(spxwPosition(account, contract, pos, avgCost))
                #print("expiration:", contract.lastTradeDateOrContractMonth, "strike:", contract.strike, "right:", contract.right, "position:", decimalMaxString(pos), "avgCost:", floatMaxString(avgCost), "len(spxwPositions_):", len(self.spxwPositions_))
            
        #print("PositionMulti. RequestId:", reqId, "Account:", account,
        #      "ModelCode:", modelCode, "Symbol:", contract.symbol, "SecType:",
        #      contract.secType, "Currency:", contract.currency, ",Position:",
        #      decimalMaxString(pos), "AvgCost:", floatMaxString(avgCost))
    # ! [positionmulti]

    @iswrapper
    # ! [positionmultiend]
    def positionMultiEnd(self, reqId: int):
        super().positionMultiEnd(reqId)
        print("PositionMultiEnd. RequestId:", reqId)
        #delete self.spxwPositions if it is not empty and move the content of self.spxwPositions_ to self.spxwPositions
        if self.spxwPositions:
            self.spxwPositions.clear()
        #print("spwPositions_(#", len(self.spxwPositions_), ") for", self.tradingDay, "and", self.nextTradingDay, "are:")
        for spxwPosition in self.spxwPositions_:
            #printinstance(spxwPosition)
            self.spxwPositions.append(spxwPosition)
        self.spxwPositions_.clear()
        #get the current trading day
        #if time is after 13:00 PDT but before midnight, then the trading day is the next day, else it is today
        self.tradingDay = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
        if datetime.datetime.now(datetime.timezone.utc).hour >= 20:
            self.tradingDay = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).strftime('%Y%m%d')
        #if tradingDay is Monday through Thursday, then the next trading day is the next day, else it is the next Monday
        if datetime.datetime.strptime(self.tradingDay, '%Y%m%d').weekday() == 3:
            self.nextTradingDay = (datetime.datetime.strptime(self.tradingDay, '%Y%m%d') + datetime.timedelta(days=3)).strftime('%Y%m%d')
        elif datetime.datetime.strptime(self.tradingDay, '%Y%m%d').weekday() == 4:
            self.nextTradingDay = (datetime.datetime.strptime(self.tradingDay, '%Y%m%d') + datetime.timedelta(days=2)).strftime('%Y%m%d')
        elif datetime.datetime.strptime(self.tradingDay, '%Y%m%d').weekday() == 5:
            self.nextTradingDay = (datetime.datetime.strptime(self.tradingDay, '%Y%m%d') + datetime.timedelta(days=1)).strftime('%Y%m%d')
        
        #print("spwPositions(#", len(self.spxwPositions), ") for", self.tradingDay, "and", self.nextTradingDay, "are:")
        #for spxwPosition in self.spxwPositions:
        #    printinstance(spxwPosition)
        

    # ! [positionmultiend]

    @iswrapper
    # ! [accountupdatemulti]
    def accountUpdateMulti(self, reqId: int, account: str, modelCode: str,
                           key: str, value: str, currency: str):
        super().accountUpdateMulti(reqId, account, modelCode, key, value,
                                   currency)
        print("AccountUpdateMulti. RequestId:", reqId, "Account:", account,
              "ModelCode:", modelCode, "Key:", key, "Value:", value,
              "Currency:", currency)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("AccountUpdateMulti. RequestId: %s Account: %s ModelCode: %s Key: %s Value: %s Currency: %s\n" % (reqId, account, modelCode, key, value, currency))
    # ! [accountupdatemulti]

    @iswrapper
    # ! [accountupdatemultiend]
    def accountUpdateMultiEnd(self, reqId: int):
        super().accountUpdateMultiEnd(reqId)
        print("AccountUpdateMultiEnd. RequestId:", reqId)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("AccountUpdateMultiEnd. RequestId: %s\n" % reqId)
    # ! [accountupdatemultiend]

    @iswrapper
    # ! [familyCodes]
    def familyCodes(self, familyCodes: ListOfFamilyCode):
        super().familyCodes(familyCodes)
        print("Family Codes:")
        for familyCode in familyCodes:
            print("FamilyCode.", familyCode)
    # ! [familyCodes]

    @iswrapper
    # ! [pnl]
    def pnl(self, reqId: int, dailyPnL: float,
            unrealizedPnL: float, realizedPnL: float):
        super().pnl(reqId, dailyPnL, unrealizedPnL, realizedPnL)
        print("Daily PnL. ReqId:", reqId, "DailyPnL:", floatMaxString(dailyPnL),
              "UnrealizedPnL:", floatMaxString(unrealizedPnL), "RealizedPnL:", floatMaxString(realizedPnL))
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("Daily PnL. ReqId: %s DailyPnL: %s UnrealizedPnL: %s RealizedPnL: %s\n" % (reqId, floatMaxString(dailyPnL), floatMaxString(unrealizedPnL), floatMaxString(realizedPnL)))
    # ! [pnl]

    @iswrapper
    # ! [pnlsingle]
    def pnlSingle(self, reqId: int, pos: Decimal, dailyPnL: float,
                  unrealizedPnL: float, realizedPnL: float, value: float):
        super().pnlSingle(reqId, pos, dailyPnL, unrealizedPnL, realizedPnL, value)
        print("Daily PnL Single. ReqId:", reqId, "Position:", decimalMaxString(pos),
              "DailyPnL:", floatMaxString(dailyPnL), "UnrealizedPnL:", floatMaxString(unrealizedPnL),
              "RealizedPnL:", floatMaxString(realizedPnL), "Value:", floatMaxString(value))
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("Daily PnL Single. ReqId: %s Position: %s DailyPnL: %s UnrealizedPnL: %s RealizedPnL: %s Value: %s\n" % (reqId, decimalMaxString(pos), floatMaxString(dailyPnL), floatMaxString(unrealizedPnL), floatMaxString(realizedPnL), floatMaxString(value)))
    # ! [pnlsingle]

    def marketDataTypeOperations(self):
        # ! [reqmarketdatatype]
        # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
        self.reqMarketDataType(MarketDataTypeEnum.DELAYED)
        # ! [reqmarketdatatype]

    @iswrapper
    # ! [marketdatatype]
    def marketDataType(self, reqId: TickerId, marketDataType: int):
        super().marketDataType(reqId, marketDataType)
        print("MarketDataType. ReqId:", reqId, "Type:", marketDataType)
        #write ESDynamicStraddleStrategy log file
        self.ESDynamicStraddleStrategy.log_file_handle.write("MarketDataType. ReqId: %s Type: %s\n" % (reqId, marketDataType))
    # ! [marketdatatype]

    @printWhenExecuting
    def tickDataOperations_req(self):
        self.reqMarketDataType(MarketDataTypeEnum.DELAYED_FROZEN)
        
        # Requesting real time market data

        # ! [reqmktdata]
        self.reqMktData(1000, ContractSamples.USStockAtSmart(), "", False, False, [])
        self.reqMktData(1001, ContractSamples.StockComboContract(), "", False, False, [])
        # ! [reqmktdata]

        # ! [reqmktdata_snapshot]
        self.reqMktData(1002, ContractSamples.FutureComboContract(), "", True, False, [])
        # ! [reqmktdata_snapshot]

        # ! [regulatorysnapshot]
        # Each regulatory snapshot request incurs a 0.01 USD fee
        self.reqMktData(1003, ContractSamples.USStock(), "", False, True, [])
        # ! [regulatorysnapshot]

        # ! [reqmktdata_genticks]
        # Requesting RTVolume (Time & Sales) and shortable generic ticks
        self.reqMktData(1004, ContractSamples.USStockAtSmart(), "233,236", False, False, [])
        # ! [reqmktdata_genticks]

        # ! [reqmktdata_contractnews]
        # Without the API news subscription this will generate an "invalid tick type" error
        self.reqMktData(1005, ContractSamples.USStockAtSmart(), "mdoff,292:BRFG", False, False, [])
        self.reqMktData(1006, ContractSamples.USStockAtSmart(), "mdoff,292:BRFG+DJNL", False, False, [])
        self.reqMktData(1007, ContractSamples.USStockAtSmart(), "mdoff,292:BRFUPDN", False, False, [])
        self.reqMktData(1008, ContractSamples.USStockAtSmart(), "mdoff,292:DJ-RT", False, False, [])
        # ! [reqmktdata_contractnews]


        # ! [reqmktdata_broadtapenews]
        self.reqMktData(1009, ContractSamples.BTbroadtapeNewsFeed(), "mdoff,292", False, False, [])
        self.reqMktData(1010, ContractSamples.BZbroadtapeNewsFeed(), "mdoff,292", False, False, [])
        self.reqMktData(1011, ContractSamples.FLYbroadtapeNewsFeed(), "mdoff,292", False, False, [])
        # ! [reqmktdata_broadtapenews]

        # ! [reqoptiondatagenticks]
        # Requesting data for an option contract will return the greek values
        self.reqMktData(1013, ContractSamples.OptionWithLocalSymbol(), "", False, False, [])
        self.reqMktData(1014, ContractSamples.FuturesOnOptions(), "", False, False, []);
        
        # ! [reqoptiondatagenticks]

        # ! [reqfuturesopeninterest]
        self.reqMktData(1015, ContractSamples.SimpleFuture(), "mdoff,588", False, False, [])
        # ! [reqfuturesopeninterest]

        # ! [reqmktdatapreopenbidask]
        self.reqMktData(1016, ContractSamples.SimpleFuture(), "", False, False, [])
        # ! [reqmktdatapreopenbidask]

        # ! [reqavgoptvolume]
        self.reqMktData(1017, ContractSamples.USStockAtSmart(), "mdoff,105", False, False, [])
        # ! [reqavgoptvolume]
        
        # ! [reqsmartcomponents]
        # Requests description of map of single letter exchange codes to full exchange names
        self.reqSmartComponents(1018, "a6")
        # ! [reqsmartcomponents]
        
        # ! [reqetfticks]
        self.reqMktData(1019, ContractSamples.etf(), "mdoff,576,577,578,623,614", False, False, [])
        # ! [reqetfticks]

        # ! [reqetfticks]
        self.reqMktData(1020, ContractSamples.StockWithIPOPrice(), "mdoff,586", False, False, [])
        # ! [reqetfticks]
        

    @printWhenExecuting
    def tickDataOperations_cancel(self):
        # Canceling the market data subscription
        # ! [cancelmktdata]
        self.cancelMktData(1000)
        self.cancelMktData(1001)
        # ! [cancelmktdata]

        self.cancelMktData(1004)
        
        self.cancelMktData(1005)
        self.cancelMktData(1006)
        self.cancelMktData(1007)
        self.cancelMktData(1008)
        
        self.cancelMktData(1009)
        self.cancelMktData(1010)
        self.cancelMktData(1011)
        self.cancelMktData(1012)
        
        self.cancelMktData(1013)
        self.cancelMktData(1014)
        
        self.cancelMktData(1015)
        
        self.cancelMktData(1016)
        
        self.cancelMktData(1017)

        self.cancelMktData(1019)
        self.cancelMktData(1020)

    @printWhenExecuting
    def tickOptionComputations_req(self):
        self.reqMarketDataType(MarketDataTypeEnum.DELAYED_FROZEN)
        # Requesting options computations
        # ! [reqoptioncomputations]
        self.reqMktData(1000, ContractSamples.OptionWithLocalSymbol(), "", False, False, [])
        # ! [reqoptioncomputations]

    @printWhenExecuting
    def tickOptionComputations_cancel(self):
        # Canceling options computations
        # ! [canceloptioncomputations]
        self.cancelMktData(1000)
        # ! [canceloptioncomputations]

    @iswrapper
    # ! [tickprice]
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float,
                  attrib: TickAttrib):
        super().tickPrice(reqId, tickType, price, attrib)
        reqContract = self.MktDataRequest[reqId]
        #print("TickPrice. TickerId:", reqId, "tickType:", tickType, "Price:", floatMaxString(price), "Attribs:", attrib)
        if reqContract.secType == "FUT" and reqContract.symbol == "ES":
            #post price update to ESDynamicStraddleStrategy
            if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK or tickType == TickTypeEnum.LAST:
                self.ESDynamicStraddleStrategy.updateESPrice(price,self)
                #self.ESDynamicStraddleStrategy.lastESPrice = self.ESDynamicStraddleStrategy.currentESPrice
                #self.ESDynamicStraddleStrategy.currentESPrice = price
        #FOP
        if reqContract.secType == "FOP":
            if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK:
                self.ESDynamicStraddleStrategy.updateESFOPPrice(reqContract, tickType, price, attrib)
                
        if False and reqContract.secType == "OPT" and reqContract.symbol == "SPX":
            if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK:
                if reqContract.lastTradeDateOrContractMonth == self.tradingDay or reqContract.lastTradeDateOrContractMonth == self.nextTradingDay:
                    #avoid duplicate entries
                    #remove all existing entries with matching reqContract and tickType
                    self.spxwPrices = [spxwPrice for spxwPrice in self.spxwPrices if not (spxwPrice.contract == reqContract and spxwPrice.tickType == tickType)]
                    self.spxwPrices.append(spxwPrice(reqContract, tickType, price, attrib))
                    print("expiration:", reqContract.lastTradeDateOrContractMonth, "strike:", reqContract.strike, "right:", reqContract.right, "tickType:", tickType, "price:", floatMaxString(price), "len(spxwPrices):", len(self.spxwPrices))
        if False and reqContract.secType == "FUT" and reqContract.symbol == "ES":
            if tickType == TickTypeEnum.BID:
                estSPXPrice = price - 57.6
                print("Bid price:", price, "PreOpen:", attrib.preOpen, "Est SPX price:", estSPXPrice)
                #is the SPX price at an integer multiple of 5?
                actionableStrike = int(estSPXPrice) - (int(estSPXPrice) % 5)
                print("SPX actionable strike:", actionableStrike)
                self.actionableStrike = actionableStrike
                if actionableStrike != None:
                    self.actionableStrikeValid = True
                    reqId = self.nextOrderId()
                    #create the contract
                    contract = Contract()
                    contract.symbol = "SPXW"
                    contract.secType = "OPT"
                    contract.exchange = "SMART"
                    contract.currency = "USD"
                    contract.lastTradeDateOrContractMonth = self.tradingDay
                    contract.strike = actionableStrike
                    contract.right = "P"
                    contract.multiplier = "100"
                    contract.tradingClass = "SPXW"
                    #request the market data
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    #request market data for +5 and -5 strikes
                    contract.strike = actionableStrike + 5
                    reqId = self.nextOrderId()
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    contract.strike = actionableStrike - 5
                    reqId = self.nextOrderId()
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    #request market data for next day
                    contract.lastTradeDateOrContractMonth = self.nextTradingDay
                    contract.strike = actionableStrike
                    reqId = self.nextOrderId()
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    contract.strike = actionableStrike + 5
                    reqId = self.nextOrderId()
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    contract.strike = actionableStrike - 5
                    reqId = self.nextOrderId()
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])

                    #request market data for margin hedges for today
                    contract.lastTradeDateOrContractMonth = self.tradingDay
                    #get next reqid
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike - 20
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike - 40
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike - 60
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    
                    #request market data for margin hedges for next day
                    contract.lastTradeDateOrContractMonth = self.nextTradingDay
                    #get next reqid
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike - 20
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike - 40
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike - 60
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])

                    #request market data for delta hedge for today
                    contract.lastTradeDateOrContractMonth = self.tradingDay
                    #get next reqid
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike + 20
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike + 40
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike + 60
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])

                    #request market data for delta hedge for next day
                    contract.lastTradeDateOrContractMonth = self.nextTradingDay
                    #get next reqid
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike + 20
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike + 40
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
                    reqId = self.nextOrderId()
                    contract.strike = actionableStrike + 60
                    self.MktDataRequest[reqId] = contract
                    self.reqMktData(reqId, contract, "", False, False, [])
            
                else:
                    self.actionableStrikeValid = False

                #check whether there is already a position in SPXW at this strike
                #get next reqid
                reqId = self.nextOrderId()
                self.reqPositionsMulti(reqId, self.account, "")
                #print the SPXW positions
                #print("spwPositions(#", len(self.spxwPositions), ") for", self.tradingDay, "and", self.nextTradingDay, "are:")
                
                #trade is possible only when actionableStrike is valid
                if self.actionableStrikeValid:
                    positionAtActionableStrikeFound = False
                    positionAboveActionableStrikeFound = False
                    positionForMarginHedgeFound = False
                    positionForMarginHedgeStrike = None
                    for spxwPosition in self.spxwPositions:
                        if spxwPosition.contract.strike == actionableStrike and spxwPosition.contract.right == "P" and spxwPosition.position < 0:
                            positionAtActionableStrikeFound = True
                            print("Found position at actionableStrike:")
                            printinstance(spxwPosition)
                        if spxwPosition.contract.strike > actionableStrike and spxwPosition.contract.right == "P" and spxwPosition.position < 0:
                            positionAboveActionableStrikeFound = True
                            print("Found position above actionableStrike:")
                            printinstance(spxwPosition)
                        if spxwPosition.contract.right == "P" and spxwPosition.position > 0:
                            positionForMarginHedgeFound = True
                            positionForMarginHedgeStrike = spxwPosition.contract.strike
                            print("Found position for margin hedge:")
                            printinstance(spxwPosition)
                            
                    if not positionAtActionableStrikeFound:
                        #short 2 SPXW put at actionableStrike
                        #for that, we first need to make sure that there are enough margin hedges in place

                        #get next reqid
                        reqId = self.nextOrderId()
                        #create the contract
                        contract = Contract()
                        contract.symbol = "SPXW"
                        contract.secType = "OPT"
                        contract.exchange = "IBUSOPT"
                        contract.currency = "USD"
                        contract.lastTradeDateOrContractMonth = self.tradingDay
                        contract.strike = actionableStrike
                        contract.right = "P"
                        contract.multiplier = "100"
                        contract.tradingClass = "SPXW"
                        #create the order pegged to mid price with offset. The offset is 0.1
                        #if not RTH, then enable trade outside RTH
                        #if during RTH, then type is IBALGO and algoStrategy is PEG MIDPRICE
                        #if outside RTH, then type is LMT and algoStrategy is PEG MIDPRICE
                        order = Order()
                        order.action = "SELL"
                        order.orderType = "MID PEG"
                        order.totalQuantity = 2
                        order.lmtPrice = 0
                        order.auxPrice = 0
                        order.algoStrategy = "PEG MIDPRICE"
                        order.algoParams = []
                        order.algoParams.append(TagValue("offset", 0.1))
                        #place the order
                        #self.placeOrder(reqId, contract, order)
                        #print("Placed order to short 2 SPXW put at actionableStrike:", actionableStrike)
                        

            
        #print("TickPrice. TickerId:", reqId, "tickType:", tickType,
        #      "Price:", floatMaxString(price), "CanAutoExecute:", attrib.canAutoExecute,
        #      "PastLimit:", attrib.pastLimit, end=' ')
        #if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK:
        #    print("PreOpen:", attrib.preOpen)
        #else:
        #    print()
    # ! [tickprice]

    @iswrapper
    # ! [ticksize]
    def tickSize(self, reqId: TickerId, tickType: TickType, size: Decimal):
        super().tickSize(reqId, tickType, size)
        #print("TickSize. TickerId:", reqId, "TickType:", tickType, "Size: ", decimalMaxString(size))
    # ! [ticksize]

    @iswrapper
    # ! [tickgeneric]
    def tickGeneric(self, reqId: TickerId, tickType: TickType, value: float):
        super().tickGeneric(reqId, tickType, value)
        #print("TickGeneric. TickerId:", reqId, "TickType:", tickType, "Value:", floatMaxString(value))
    # ! [tickgeneric]

    @iswrapper
    # ! [tickstring]
    def tickString(self, reqId: TickerId, tickType: TickType, value: str):
        super().tickString(reqId, tickType, value)
        #print("TickString. TickerId:", reqId, "Type:", tickType, "Value:", value)
    # ! [tickstring]

    @iswrapper
    # ! [ticksnapshotend]
    def tickSnapshotEnd(self, reqId: int):
        super().tickSnapshotEnd(reqId)
        print("TickSnapshotEnd. TickerId:", reqId)
    # ! [ticksnapshotend]

    @iswrapper
    # ! [rerouteMktDataReq]
    def rerouteMktDataReq(self, reqId: int, conId: int, exchange: str):
        super().rerouteMktDataReq(reqId, conId, exchange)
        print("Re-route market data request. ReqId:", reqId, "ConId:", conId, "Exchange:", exchange)
    # ! [rerouteMktDataReq]

    @iswrapper
    # ! [marketRule]
    def marketRule(self, marketRuleId: int, priceIncrements: ListOfPriceIncrements):
        super().marketRule(marketRuleId, priceIncrements)
        print("Market Rule ID: ", marketRuleId)
        for priceIncrement in priceIncrements:
            print("Price Increment.", priceIncrement)
    # ! [marketRule]

    @printWhenExecuting
    def tickByTickOperations_req(self):
        # Requesting tick-by-tick data (only refresh)
        # ! [reqtickbytick]
        self.reqTickByTickData(19001, ContractSamples.EuropeanStock2(), "Last", 0, True)
        self.reqTickByTickData(19002, ContractSamples.EuropeanStock2(), "AllLast", 0, False)
        self.reqTickByTickData(19003, ContractSamples.EuropeanStock2(), "BidAsk", 0, True)
        self.reqTickByTickData(19004, ContractSamples.EurGbpFx(), "MidPoint", 0, False)
        # ! [reqtickbytick]

        # Requesting tick-by-tick data (refresh + historicalticks)
        # ! [reqtickbytickwithhist]
        self.reqTickByTickData(19005, ContractSamples.EuropeanStock2(), "Last", 10, False)
        self.reqTickByTickData(19006, ContractSamples.EuropeanStock2(), "AllLast", 10, False)
        self.reqTickByTickData(19007, ContractSamples.EuropeanStock2(), "BidAsk", 10, False)
        self.reqTickByTickData(19008, ContractSamples.EurGbpFx(), "MidPoint", 10, True)
        # ! [reqtickbytickwithhist]

    @printWhenExecuting
    def tickByTickOperations_cancel(self):
        # ! [canceltickbytick]
        self.cancelTickByTickData(19001)
        self.cancelTickByTickData(19002)
        self.cancelTickByTickData(19003)
        self.cancelTickByTickData(19004)
        # ! [canceltickbytick]

        # ! [canceltickbytickwithhist]
        self.cancelTickByTickData(19005)
        self.cancelTickByTickData(19006)
        self.cancelTickByTickData(19007)
        self.cancelTickByTickData(19008)
        # ! [canceltickbytickwithhist]
        
    @iswrapper
    # ! [orderbound]
    def orderBound(self, orderId: int, apiClientId: int, apiOrderId: int):
        super().orderBound(orderId, apiClientId, apiOrderId)
        print("OrderBound.", "OrderId:", intMaxString(orderId), "ApiClientId:", intMaxString(apiClientId), "ApiOrderId:", intMaxString(apiOrderId))
    # ! [orderbound]

    @iswrapper
    # ! [tickbytickalllast]
    def tickByTickAllLast(self, reqId: int, tickType: int, time: int, price: float,
                          size: Decimal, tickAtrribLast: TickAttribLast, exchange: str,
                          specialConditions: str):
        super().tickByTickAllLast(reqId, tickType, time, price, size, tickAtrribLast,
                                  exchange, specialConditions)
        if tickType == 1:
            print("Last.", end='')
        else:
            print("AllLast.", end='')
        print(" ReqId:", reqId,
              "Time:", datetime.datetime.fromtimestamp(time).strftime("%Y%m%d-%H:%M:%S"),
              "Price:", floatMaxString(price), "Size:", decimalMaxString(size), "Exch:" , exchange,
              "Spec Cond:", specialConditions, "PastLimit:", tickAtrribLast.pastLimit, "Unreported:", tickAtrribLast.unreported)
    # ! [tickbytickalllast]

    @iswrapper
    # ! [tickbytickbidask]
    def tickByTickBidAsk(self, reqId: int, time: int, bidPrice: float, askPrice: float,
                         bidSize: Decimal, askSize: Decimal, tickAttribBidAsk: TickAttribBidAsk):
        super().tickByTickBidAsk(reqId, time, bidPrice, askPrice, bidSize,
                                 askSize, tickAttribBidAsk)
        print("BidAsk. ReqId:", reqId,
              "Time:", datetime.datetime.fromtimestamp(time).strftime("%Y%m%d-%H:%M:%S"),
              "BidPrice:", floatMaxString(bidPrice), "AskPrice:", floatMaxString(askPrice), "BidSize:", decimalMaxString(bidSize),
              "AskSize:", decimalMaxString(askSize), "BidPastLow:", tickAttribBidAsk.bidPastLow, "AskPastHigh:", tickAttribBidAsk.askPastHigh)
    # ! [tickbytickbidask]

    # ! [tickbytickmidpoint]
    @iswrapper
    def tickByTickMidPoint(self, reqId: int, time: int, midPoint: float):
        super().tickByTickMidPoint(reqId, time, midPoint)
        print("Midpoint. ReqId:", reqId,
              "Time:", datetime.datetime.fromtimestamp(time).strftime("%Y%m%d-%H:%M:%S"),
              "MidPoint:", floatMaxString(midPoint))
    # ! [tickbytickmidpoint]

    @printWhenExecuting
    def marketDepthOperations_req(self):
        # Requesting the Deep Book
        # ! [reqmarketdepth]
        self.reqMktDepth(2001, ContractSamples.EurGbpFx(), 5, False, [])
        # ! [reqmarketdepth]

        # ! [reqmarketdepth]
        self.reqMktDepth(2002, ContractSamples.EuropeanStock(), 5, True, [])
        # ! [reqmarketdepth]

        # Request list of exchanges sending market depth to UpdateMktDepthL2()
        # ! [reqMktDepthExchanges]
        self.reqMktDepthExchanges()
        # ! [reqMktDepthExchanges]

    @printWhenExecuting
    def marketDepthOperations_cancel(self):
        # Canceling the Deep Book request
        # ! [cancelmktdepth]
        self.cancelMktDepth(2001, False)
        self.cancelMktDepth(2002, True)
        # ! [cancelmktdepth]

    @iswrapper
    # ! [updatemktdepth]
    def updateMktDepth(self, reqId: TickerId, position: int, operation: int,
                       side: int, price: float, size: Decimal):
        super().updateMktDepth(reqId, position, operation, side, price, size)
        print("UpdateMarketDepth. ReqId:", reqId, "Position:", position, "Operation:",
              operation, "Side:", side, "Price:", floatMaxString(price), "Size:", decimalMaxString(size))
    # ! [updatemktdepth]

    @iswrapper
    # ! [updatemktdepthl2]
    def updateMktDepthL2(self, reqId: TickerId, position: int, marketMaker: str,
                         operation: int, side: int, price: float, size: Decimal, isSmartDepth: bool):
        super().updateMktDepthL2(reqId, position, marketMaker, operation, side,
                                 price, size, isSmartDepth)
        print("UpdateMarketDepthL2. ReqId:", reqId, "Position:", position, "MarketMaker:", marketMaker, "Operation:",
              operation, "Side:", side, "Price:", floatMaxString(price), "Size:", decimalMaxString(size), "isSmartDepth:", isSmartDepth)

    # ! [updatemktdepthl2]

    @iswrapper
    # ! [rerouteMktDepthReq]
    def rerouteMktDepthReq(self, reqId: int, conId: int, exchange: str):
        super().rerouteMktDataReq(reqId, conId, exchange)
        print("Re-route market depth request. ReqId:", reqId, "ConId:", conId, "Exchange:", exchange)
    # ! [rerouteMktDepthReq]

    @printWhenExecuting
    def realTimeBarsOperations_req(self):
        # Requesting real time bars
        # ! [reqrealtimebars]
        self.reqRealTimeBars(3001, ContractSamples.EurGbpFx(), 5, "MIDPOINT", True, [])
        # ! [reqrealtimebars]

    @iswrapper
    # ! [realtimebar]
    def realtimeBar(self, reqId: TickerId, time:int, open_: float, high: float, low: float, close: float,
                        volume: Decimal, wap: Decimal, count: int):
        super().realtimeBar(reqId, time, open_, high, low, close, volume, wap, count)
        print("RealTimeBar. TickerId:", reqId, RealTimeBar(time, -1, open_, high, low, close, volume, wap, count))
    # ! [realtimebar]

    @printWhenExecuting
    def realTimeBarsOperations_cancel(self):
        # Canceling real time bars
        # ! [cancelrealtimebars]
        self.cancelRealTimeBars(3001)
        # ! [cancelrealtimebars]

    @printWhenExecuting
    def historicalDataOperations_req(self):
        # Requesting historical data
        # ! [reqHeadTimeStamp]
        self.reqHeadTimeStamp(4101, ContractSamples.USStockAtSmart(), "TRADES", 0, 1)
        # ! [reqHeadTimeStamp]

        # ! [reqhistoricaldata]
        queryTime = (datetime.datetime.today() - datetime.timedelta(days=180)).strftime("%Y%m%d-%H:%M:%S")
        self.reqHistoricalData(4102, ContractSamples.EurGbpFx(), queryTime,
                               "1 M", "1 day", "MIDPOINT", 1, 1, False, [])
        self.reqHistoricalData(4103, ContractSamples.EuropeanStock(), queryTime,
                               "10 D", "1 min", "TRADES", 1, 1, False, [])
        self.reqHistoricalData(4104, ContractSamples.EurGbpFx(), "",
                               "1 M", "1 day", "MIDPOINT", 1, 1, True, [])
        self.reqHistoricalData(4103, ContractSamples.USStockAtSmart(), queryTime,
                               "1 M", "1 day", "SCHEDULE", 1, 1, False, [])
        # ! [reqhistoricaldata]

    @printWhenExecuting
    def historicalDataOperations_cancel(self):
        # ! [cancelHeadTimestamp]
        self.cancelHeadTimeStamp(4101)
        # ! [cancelHeadTimestamp]
        
        # Canceling historical data requests
        # ! [cancelhistoricaldata]
        self.cancelHistoricalData(4102)
        self.cancelHistoricalData(4103)
        self.cancelHistoricalData(4104)
        # ! [cancelhistoricaldata]

    @printWhenExecuting
    def historicalTicksOperations(self):
        # ! [reqhistoricalticks]
        self.reqHistoricalTicks(18001, ContractSamples.USStockAtSmart(),
                                "20170712 21:39:33 US/Eastern", "", 10, "TRADES", 1, True, [])
        self.reqHistoricalTicks(18002, ContractSamples.USStockAtSmart(),
                                "20170712 21:39:33 US/Eastern", "", 10, "BID_ASK", 1, True, [])
        self.reqHistoricalTicks(18003, ContractSamples.USStockAtSmart(),
                                "20170712 21:39:33 US/Eastern", "", 10, "MIDPOINT", 1, True, [])
        # ! [reqhistoricalticks]

    @iswrapper
    # ! [headTimestamp]
    def headTimestamp(self, reqId:int, headTimestamp:str):
        print("HeadTimestamp. ReqId:", reqId, "HeadTimeStamp:", headTimestamp)
    # ! [headTimestamp]

    @iswrapper
    # ! [histogramData]
    def histogramData(self, reqId:int, items:HistogramDataList):
        print("HistogramData. ReqId:", reqId, "HistogramDataList:", "[%s]" % "; ".join(map(str, items)))
    # ! [histogramData]

    @iswrapper
    # ! [historicaldata]
    def historicalData(self, reqId:int, bar: BarData):
        print("HistoricalData. ReqId:", reqId, "BarData.", bar)
    # ! [historicaldata]

    @iswrapper
    # ! [historicaldataend]
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        print("HistoricalDataEnd. ReqId:", reqId, "from", start, "to", end)
    # ! [historicaldataend]

    @iswrapper
    # ! [historicalDataUpdate]
    def historicalDataUpdate(self, reqId: int, bar: BarData):
        print("HistoricalDataUpdate. ReqId:", reqId, "BarData.", bar)
    # ! [historicalDataUpdate]

    @iswrapper
    # ! [historicalticks]
    def historicalTicks(self, reqId: int, ticks: ListOfHistoricalTick, done: bool):
        for tick in ticks:
            print("HistoricalTick. ReqId:", reqId, tick)
    # ! [historicalticks]

    @iswrapper
    # ! [historicalticksbidask]
    def historicalTicksBidAsk(self, reqId: int, ticks: ListOfHistoricalTickBidAsk,
                              done: bool):
        for tick in ticks:
            print("HistoricalTickBidAsk. ReqId:", reqId, tick)
    # ! [historicalticksbidask]

    @iswrapper
    # ! [historicaltickslast]
    def historicalTicksLast(self, reqId: int, ticks: ListOfHistoricalTickLast,
                            done: bool):
        for tick in ticks:
            print("HistoricalTickLast. ReqId:", reqId, tick)
    # ! [historicaltickslast]

    @printWhenExecuting
    def optionsOperations_req(self):
        # ! [reqsecdefoptparams]
        self.reqSecDefOptParams(0, "IBM", "", "STK", 8314)
        # ! [reqsecdefoptparams]

        # Calculating implied volatility
        # ! [calculateimpliedvolatility]
        self.calculateImpliedVolatility(5001, ContractSamples.OptionWithLocalSymbol(), 0.5, 55, [])
        # ! [calculateimpliedvolatility]

        # Calculating option's price
        # ! [calculateoptionprice]
        self.calculateOptionPrice(5002, ContractSamples.OptionWithLocalSymbol(), 0.6, 55, [])
        # ! [calculateoptionprice]

        # Exercising options
        # ! [exercise_options]
        self.exerciseOptions(5003, ContractSamples.OptionWithTradingClass(), 1,
                             1, self.account, 1)
        # ! [exercise_options]

    @printWhenExecuting
    def optionsOperations_cancel(self):
        # Canceling implied volatility
        self.cancelCalculateImpliedVolatility(5001)
        # Canceling option's price calculation
        self.cancelCalculateOptionPrice(5002)

    @iswrapper
    # ! [securityDefinitionOptionParameter]
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str,
                                          underlyingConId: int, tradingClass: str, multiplier: str,
                                          expirations: SetOfString, strikes: SetOfFloat):
        super().securityDefinitionOptionParameter(reqId, exchange,
                                                  underlyingConId, tradingClass, multiplier, expirations, strikes)
        print("SecurityDefinitionOptionParameter.",
              "ReqId:", reqId, "Exchange:", exchange, "Underlying conId:", intMaxString(underlyingConId), "TradingClass:", tradingClass, "Multiplier:", multiplier,
              "Expirations:", expirations, "Strikes:", str(strikes))
    # ! [securityDefinitionOptionParameter]

    @iswrapper
    # ! [securityDefinitionOptionParameterEnd]
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        super().securityDefinitionOptionParameterEnd(reqId)
        print("SecurityDefinitionOptionParameterEnd. ReqId:", reqId)
    # ! [securityDefinitionOptionParameterEnd]

    @iswrapper
    # ! [tickoptioncomputation]
    def tickOptionComputation(self, reqId: TickerId, tickType: TickType, tickAttrib: int,
                              impliedVol: float, delta: float, optPrice: float, pvDividend: float,
                              gamma: float, vega: float, theta: float, undPrice: float):
        #super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta,
        #                              optPrice, pvDividend, gamma, vega, theta, undPrice)
        #print("TickOptionComputation. TickerId:", reqId, "TickType:", tickType,
        #      "TickAttrib:", intMaxString(tickAttrib),
              #"ImpliedVolatility:", floatMaxString(impliedVol),
              #"Delta:", floatMaxString(delta),
        #      "OptionPrice:", optPrice,
              #"pvDividend:", floatMaxString(pvDividend), "Gamma: ", floatMaxString(gamma), "Vega:", floatMaxString(vega),
              #"Theta:", floatMaxString(theta),
        #      "UnderlyingPrice:", floatMaxString(undPrice))
        reqContract = self.MktDataRequest[reqId]
        if reqContract.secType == "OPT" and reqContract.symbol == "SPX":
            if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK:
                if reqContract.lastTradeDateOrContractMonth == self.tradingDay or reqContract.lastTradeDateOrContractMonth == self.nextTradingDay:
                    #avoid duplicate entries
                    #remove all existing entries with matching reqContract and tickType
                    self.spxwPrices = [spxwPrice for spxwPrice in self.spxwPrices if not (spxwPrice.contract == reqContract and spxwPrice.tickType == tickType)]
                    self.spxwPrices.append(spxwPrice(reqContract, tickType, optPrice, tickAttrib))
                    print("expiration:", reqContract.lastTradeDateOrContractMonth, "strike:", reqContract.strike, "right:", reqContract.right, "tickType:", tickType, "price:", floatMaxString(optPrice), "len(spxwPrices):", len(self.spxwPrices))
        #FOP
        if reqContract.secType == "FOP":
            if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK:
                self.ESDynamicStraddleStrategy.updateESFOPPrice(reqContract, tickType, optPrice, tickAttrib)

    # ! [tickoptioncomputation]

    @printWhenExecuting
    def contractOperations_SPXW(self):
        #get ES streaming quote
        #make contract for ES
        contract = Contract()
        contract.symbol = "ES"
        contract.secType = "FUT"
        contract.exchange = "CME"
        contract.currency = "USD"
        contract.lastTradeDateOrContractMonth = "20240621"
        #get reqId
        reqId = self.nextOrderId()
        self.MktDataRequest[reqId] = contract
        #get ES streaming quote
        self.reqMktData(reqId, contract, "", False, False, [])

    @printWhenExecuting
    def contractOperations(self):
        # ! [reqcontractdetails]
        self.reqContractDetails(210, ContractSamples.OptionForQuery())
        self.reqContractDetails(211, ContractSamples.EurGbpFx())
        self.reqContractDetails(212, ContractSamples.Bond())
        self.reqContractDetails(213, ContractSamples.FuturesOnOptions())
        self.reqContractDetails(214, ContractSamples.SimpleFuture())
        self.reqContractDetails(215, ContractSamples.USStockAtSmart())
        self.reqContractDetails(216, ContractSamples.CryptoContract())
        self.reqContractDetails(217, ContractSamples.ByIssuerId())
        # ! [reqcontractdetails]

        # ! [reqmatchingsymbols]
        self.reqMatchingSymbols(218, "IBM")
        # ! [reqmatchingsymbols]

    @printWhenExecuting
    def newsOperations_req(self):
        # Requesting news ticks
        # ! [reqNewsTicks]
        self.reqMktData(10001, ContractSamples.USStockAtSmart(), "mdoff,292", False, False, []);
        # ! [reqNewsTicks]

        # Returns list of subscribed news providers
        # ! [reqNewsProviders]
        self.reqNewsProviders()
        # ! [reqNewsProviders]

        # Returns body of news article given article ID
        # ! [reqNewsArticle]
        self.reqNewsArticle(10002,"BRFG", "BRFG$04fb9da2", [])
        # ! [reqNewsArticle]

        # Returns list of historical news headlines with IDs
        # ! [reqHistoricalNews]
        self.reqHistoricalNews(10003, 8314, "BRFG", "", "", 10, [])
        # ! [reqHistoricalNews]

        # ! [reqcontractdetailsnews]
        self.reqContractDetails(10004, ContractSamples.NewsFeedForQuery())
        # ! [reqcontractdetailsnews]

    @printWhenExecuting
    def newsOperations_cancel(self):
        # Canceling news ticks
        # ! [cancelNewsTicks]
        self.cancelMktData(10001);
        # ! [cancelNewsTicks]

    @iswrapper
    #! [tickNews]
    def tickNews(self, tickerId: int, timeStamp: int, providerCode: str,
                 articleId: str, headline: str, extraData: str):
        print("TickNews. TickerId:", tickerId, "TimeStamp:", intMaxString(timeStamp),
              "ProviderCode:", providerCode, "ArticleId:", articleId,
              "Headline:", headline, "ExtraData:", extraData)
    #! [tickNews]

    @iswrapper
    #! [historicalNews]
    def historicalNews(self, reqId: int, time: str, providerCode: str,
                       articleId: str, headline: str):
        print("HistoricalNews. ReqId:", reqId, "Time:", time,
              "ProviderCode:", providerCode, "ArticleId:", articleId,
              "Headline:", headline)
    #! [historicalNews]

    @iswrapper
    #! [historicalNewsEnd]
    def historicalNewsEnd(self, reqId:int, hasMore:bool):
        print("HistoricalNewsEnd. ReqId:", reqId, "HasMore:", hasMore)
    #! [historicalNewsEnd]

    @iswrapper
    #! [newsProviders]
    def newsProviders(self, newsProviders: ListOfNewsProviders):
        print("NewsProviders: ")
        for provider in newsProviders:
            print("NewsProvider.", provider)
    #! [newsProviders]

    @iswrapper
    #! [newsArticle]
    def newsArticle(self, reqId: int, articleType: int, articleText: str):
        print("NewsArticle. ReqId:", reqId, "ArticleType:", articleType,
              "ArticleText:", articleText)
    #! [newsArticle]

    @iswrapper
    # ! [contractdetails]
    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        super().contractDetails(reqId, contractDetails)
        printinstance(contractDetails)
    # ! [contractdetails]

    @iswrapper
    # ! [bondcontractdetails]
    def bondContractDetails(self, reqId: int, contractDetails: ContractDetails):
        super().bondContractDetails(reqId, contractDetails)
        printinstance(contractDetails)
    # ! [bondcontractdetails]

    @iswrapper
    # ! [contractdetailsend]
    def contractDetailsEnd(self, reqId: int):
        super().contractDetailsEnd(reqId)
        print("ContractDetailsEnd. ReqId:", reqId)
    # ! [contractdetailsend]

    @iswrapper
    # ! [symbolSamples]
    def symbolSamples(self, reqId: int,
                      contractDescriptions: ListOfContractDescription):
        super().symbolSamples(reqId, contractDescriptions)
        print("Symbol Samples. Request Id: ", reqId)

        for contractDescription in contractDescriptions:
            derivSecTypes = ""
            for derivSecType in contractDescription.derivativeSecTypes:
                derivSecTypes += " "
                derivSecTypes += derivSecType
            print("Contract: conId:%s, symbol:%s, secType:%s primExchange:%s, "
                  "currency:%s, derivativeSecTypes:%s, description:%s, issuerId:%s" % (
                contractDescription.contract.conId,
                contractDescription.contract.symbol,
                contractDescription.contract.secType,
                contractDescription.contract.primaryExchange,
                contractDescription.contract.currency, derivSecTypes,
                contractDescription.contract.description,
                contractDescription.contract.issuerId))
    # ! [symbolSamples]

    @printWhenExecuting
    def marketScannersOperations_req(self):
        # Requesting list of valid scanner parameters which can be used in TWS
        # ! [reqscannerparameters]
        self.reqScannerParameters()
        # ! [reqscannerparameters]

        # Triggering a scanner subscription
        # ! [reqscannersubscription]
        self.reqScannerSubscription(7001, ScannerSubscriptionSamples.HighOptVolumePCRatioUSIndexes(), [], [])

        # Generic Filters
        tagvalues = []
        tagvalues.append(TagValue("usdMarketCapAbove", "10000"))
        tagvalues.append(TagValue("optVolumeAbove", "1000"))
        tagvalues.append(TagValue("avgVolumeAbove", "10000"));

        self.reqScannerSubscription(7002, ScannerSubscriptionSamples.HotUSStkByVolume(), [], tagvalues) # requires TWS v973+
        # ! [reqscannersubscription]

        # ! [reqcomplexscanner]
        AAPLConIDTag = [TagValue("underConID", "265598")]
        self.reqScannerSubscription(7003, ScannerSubscriptionSamples.ComplexOrdersAndTrades(), [], AAPLConIDTag) # requires TWS v975+
        
        # ! [reqcomplexscanner]


    @printWhenExecuting
    def marketScanners_cancel(self):
        # Canceling the scanner subscription
        # ! [cancelscannersubscription]
        self.cancelScannerSubscription(7001)
        self.cancelScannerSubscription(7002)
        self.cancelScannerSubscription(7003)
        # ! [cancelscannersubscription]

    @iswrapper
    # ! [scannerparameters]
    def scannerParameters(self, xml: str):
        super().scannerParameters(xml)
        open('log/scanner.xml', 'w').write(xml)
        print("ScannerParameters received.")
    # ! [scannerparameters]

    @iswrapper
    # ! [scannerdata]
    def scannerData(self, reqId: int, rank: int, contractDetails: ContractDetails,
                    distance: str, benchmark: str, projection: str, legsStr: str):
        super().scannerData(reqId, rank, contractDetails, distance, benchmark,
                            projection, legsStr)
#        print("ScannerData. ReqId:", reqId, "Rank:", rank, "Symbol:", contractDetails.contract.symbol,
#              "SecType:", contractDetails.contract.secType,
#              "Currency:", contractDetails.contract.currency,
#              "Distance:", distance, "Benchmark:", benchmark,
#              "Projection:", projection, "Legs String:", legsStr)
        print("ScannerData. ReqId:", reqId, ScanData(contractDetails.contract, rank, distance, benchmark, projection, legsStr))
    # ! [scannerdata]

    @iswrapper
    # ! [scannerdataend]
    def scannerDataEnd(self, reqId: int):
        super().scannerDataEnd(reqId)
        print("ScannerDataEnd. ReqId:", reqId)
        # ! [scannerdataend]

    @iswrapper
    # ! [smartcomponents]
    def smartComponents(self, reqId:int, smartComponentMap:SmartComponentMap):
        super().smartComponents(reqId, smartComponentMap)
        print("SmartComponents:")
        for smartComponent in smartComponentMap:
            print("SmartComponent.", smartComponent)
    # ! [smartcomponents]

    @iswrapper
    # ! [tickReqParams]
    def tickReqParams(self, tickerId:int, minTick:float,
                      bboExchange:str, snapshotPermissions:int):
        super().tickReqParams(tickerId, minTick, bboExchange, snapshotPermissions)
        print("TickReqParams. TickerId:", tickerId, "MinTick:", floatMaxString(minTick),
              "BboExchange:", bboExchange, "SnapshotPermissions:", intMaxString(snapshotPermissions))
    # ! [tickReqParams]

    @iswrapper
    # ! [mktDepthExchanges]
    def mktDepthExchanges(self, depthMktDataDescriptions:ListOfDepthExchanges):
        super().mktDepthExchanges(depthMktDataDescriptions)
        print("MktDepthExchanges:")
        for desc in depthMktDataDescriptions:
            print("DepthMktDataDescription.", desc)
    # ! [mktDepthExchanges]

    @printWhenExecuting
    def fundamentalsOperations_req(self):
        # Requesting Fundamentals
        # ! [reqfundamentaldata]
        self.reqFundamentalData(8001, ContractSamples.USStock(), "ReportsFinSummary", [])
        # ! [reqfundamentaldata]
        
        # ! [fundamentalexamples]
        self.reqFundamentalData(8002, ContractSamples.USStock(), "ReportSnapshot", []); # for company overview
        self.reqFundamentalData(8003, ContractSamples.USStock(), "ReportRatios", []); # for financial ratios
        self.reqFundamentalData(8004, ContractSamples.USStock(), "ReportsFinStatements", []); # for financial statements
        self.reqFundamentalData(8005, ContractSamples.USStock(), "RESC", []); # for analyst estimates
        self.reqFundamentalData(8006, ContractSamples.USStock(), "CalendarReport", []); # for company calendar
        # ! [fundamentalexamples]

    @printWhenExecuting
    def fundamentalsOperations_cancel(self):
        # Canceling fundamentalsOperations_req request
        # ! [cancelfundamentaldata]
        self.cancelFundamentalData(8001)
        # ! [cancelfundamentaldata]

        # ! [cancelfundamentalexamples]
        self.cancelFundamentalData(8002)
        self.cancelFundamentalData(8003)
        self.cancelFundamentalData(8004)
        self.cancelFundamentalData(8005)
        self.cancelFundamentalData(8006)
        # ! [cancelfundamentalexamples]

    @iswrapper
    # ! [fundamentaldata]
    def fundamentalData(self, reqId: TickerId, data: str):
        super().fundamentalData(reqId, data)
        print("FundamentalData. ReqId:", reqId, "Data:", data)
    # ! [fundamentaldata]

    @printWhenExecuting
    def bulletinsOperations_req(self):
        # Requesting Interactive Broker's news bulletinsOperations_req
        # ! [reqnewsbulletins]
        self.reqNewsBulletins(True)
        # ! [reqnewsbulletins]

    @printWhenExecuting
    def bulletinsOperations_cancel(self):
        # Canceling IB's news bulletinsOperations_req
        # ! [cancelnewsbulletins]
        self.cancelNewsBulletins()
        # ! [cancelnewsbulletins]

    @iswrapper
    # ! [updatenewsbulletin]
    def updateNewsBulletin(self, msgId: int, msgType: int, newsMessage: str,
                           originExch: str):
        super().updateNewsBulletin(msgId, msgType, newsMessage, originExch)
        print("News Bulletins. MsgId:", msgId, "Type:", msgType, "Message:", newsMessage,
              "Exchange of Origin: ", originExch)
        # ! [updatenewsbulletin]

    def ocaSample(self):
        # OCA ORDER
        # ! [ocasubmit]
        ocaOrders = [OrderSamples.LimitOrder("BUY", 1, 10), OrderSamples.LimitOrder("BUY", 1, 11),
                     OrderSamples.LimitOrder("BUY", 1, 12)]
        OrderSamples.OneCancelsAll("TestOCA_" + str(self.nextValidOrderId), ocaOrders, 2)
        for o in ocaOrders:
            self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), o)
            # ! [ocasubmit]

    def conditionSamples(self):
        # ! [order_conditioning_activate]
        mkt = OrderSamples.MarketOrder("BUY", 100)
        # Order will become active if conditioning criteria is met
        mkt.conditions.append(
            OrderSamples.PriceCondition(PriceCondition.TriggerMethodEnum.Default,
                                        208813720, "SMART", 600, False, False))
        mkt.conditions.append(OrderSamples.ExecutionCondition("EUR.USD", "CASH", "IDEALPRO", True))
        mkt.conditions.append(OrderSamples.MarginCondition(30, True, False))
        mkt.conditions.append(OrderSamples.PercentageChangeCondition(15.0, 208813720, "SMART", True, True))
        mkt.conditions.append(OrderSamples.TimeCondition("20160118 23:59:59 US/Eastern", True, False))
        mkt.conditions.append(OrderSamples.VolumeCondition(208813720, "SMART", False, 100, True))
        self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), mkt)
        # ! [order_conditioning_activate]

        # Conditions can make the order active or cancel it. Only LMT orders can be conditionally canceled.
        # ! [order_conditioning_cancel]
        lmt = OrderSamples.LimitOrder("BUY", 100, 20)
        # The active order will be cancelled if conditioning criteria is met
        lmt.conditionsCancelOrder = True
        lmt.conditions.append(
            OrderSamples.PriceCondition(PriceCondition.TriggerMethodEnum.Last,
                                        208813720, "SMART", 600, False, False))
        self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), lmt)
        # ! [order_conditioning_cancel]

    def bracketSample(self):
        # BRACKET ORDER
        # ! [bracketsubmit]
        bracket = OrderSamples.BracketOrder(self.nextOrderId(), "BUY", 100, 30, 40, 20)
        for o in bracket:
            self.placeOrder(o.orderId, ContractSamples.EuropeanStock(), o)
            self.nextOrderId()  # need to advance this we'll skip one extra oid, it's fine
            # ! [bracketsubmit]

    def hedgeSample(self):
        # F Hedge order
        # ! [hedgesubmit]
        # Parent order on a contract which currency differs from your base currency
        parent = OrderSamples.LimitOrder("BUY", 100, 10)
        parent.orderId = self.nextOrderId()
        parent.transmit = False
        # Hedge on the currency conversion
        hedge = OrderSamples.MarketFHedge(parent.orderId, "BUY")
        # Place the parent first...
        self.placeOrder(parent.orderId, ContractSamples.EuropeanStock(), parent)
        # Then the hedge order
        self.placeOrder(self.nextOrderId(), ContractSamples.EurGbpFx(), hedge)
        # ! [hedgesubmit]

    def algoSamples(self):
        # ! [scale_order]
        scaleOrder = OrderSamples.RelativePeggedToPrimary("BUY",  70000,  189,  0.01);
        AvailableAlgoParams.FillScaleParams(scaleOrder, 2000, 500, True, .02, 189.00, 3600, 2.00, True, 10, 40);
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), scaleOrder);
        # ! [scale_order]

        time.sleep(1)

        # ! [algo_base_order]
        baseOrder = OrderSamples.LimitOrder("BUY", 1000, 1)
        # ! [algo_base_order]

        # ! [arrivalpx]
        AvailableAlgoParams.FillArrivalPriceParams(baseOrder, 0.1, "Aggressive", "09:00:00 US/Eastern", "16:00:00 US/Eastern", True, True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [arrivalpx]

        # ! [darkice]
        AvailableAlgoParams.FillDarkIceParams(baseOrder, 10, "09:00:00 US/Eastern", "16:00:00 US/Eastern", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [darkice]

        # ! [place_midprice]
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), OrderSamples.Midprice("BUY", 1, 150))
        # ! [place_midprice]

        # ! [ad]
        # The Time Zone in "startTime" and "endTime" attributes is ignored and always defaulted to GMT
        AvailableAlgoParams.FillAccumulateDistributeParams(baseOrder, 10, 60, True, True, 1, True, True, "12:00:00", "16:00:00")
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [ad]

        # ! [twap]
        AvailableAlgoParams.FillTwapParams(baseOrder, "Marketable", "09:00:00 US/Eastern", "16:00:00 US/Eastern", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [twap]

        # ! [vwap]
        AvailableAlgoParams.FillVwapParams(baseOrder, 0.2, "09:00:00 US/Eastern", "16:00:00 US/Eastern", True, True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [vwap]

        # ! [balanceimpactrisk]
        AvailableAlgoParams.FillBalanceImpactRiskParams(baseOrder, 0.1, "Aggressive", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USOptionContract(), baseOrder)
        # ! [balanceimpactrisk]

        # ! [minimpact]
        AvailableAlgoParams.FillMinImpactParams(baseOrder, 0.3)
        self.placeOrder(self.nextOrderId(), ContractSamples.USOptionContract(), baseOrder)
        # ! [minimpact]

        # ! [adaptive]
        AvailableAlgoParams.FillAdaptiveParams(baseOrder, "Normal")
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [adaptive]

        # ! [closepx]
        AvailableAlgoParams.FillClosePriceParams(baseOrder, 0.4, "Neutral", "20180926-06:06:49", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [closepx]

        # ! [pctvol]
        AvailableAlgoParams.FillPctVolParams(baseOrder, 0.5, "12:00:00 US/Eastern", "14:00:00 US/Eastern", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [pctvol]

        # ! [pctvolpx]
        AvailableAlgoParams.FillPriceVariantPctVolParams(baseOrder, 0.1, 0.05, 0.01, 0.2, "12:00:00 US/Eastern", "14:00:00 US/Eastern", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [pctvolpx]

        # ! [pctvolsz]
        AvailableAlgoParams.FillSizeVariantPctVolParams(baseOrder, 0.2, 0.4, "12:00:00 US/Eastern", "14:00:00 US/Eastern", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [pctvolsz]

        # ! [pctvoltm]
        AvailableAlgoParams.FillTimeVariantPctVolParams(baseOrder, 0.2, 0.4, "12:00:00 US/Eastern", "14:00:00 US/Eastern", True)
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), baseOrder)
        # ! [pctvoltm]

        # ! [jeff_vwap_algo]
        AvailableAlgoParams.FillJefferiesVWAPParams(baseOrder, "10:00:00 US/Eastern", "16:00:00 US/Eastern", 10, 10, "Exclude_Both", 130, 135, 1, 10, "Patience", False, "Midpoint")
        self.placeOrder(self.nextOrderId(), ContractSamples.JefferiesContract(), baseOrder)
        # ! [jeff_vwap_algo]

        # ! [csfb_inline_algo]
        AvailableAlgoParams.FillCSFBInlineParams(baseOrder, "10:00:00 US/Eastern", "16:00:00 US/Eastern", "Patient", 10, 20, 100, "Default", False, 40, 100, 100, 35)
        self.placeOrder(self.nextOrderId(), ContractSamples.CSFBContract(), baseOrder)
        # ! [csfb_inline_algo]

        # ! [qbalgo_strobe_algo]
        AvailableAlgoParams.FillQBAlgoInLineParams(baseOrder, "10:00:00 US/Eastern", "16:00:00 US/Eastern", -99, "TWAP", 0.25, True)
        self.placeOrder(self.nextOrderId(), ContractSamples.QBAlgoContract(), baseOrder)
        # ! [qbalgo_strobe_algo]

    @printWhenExecuting
    def financialAdvisorOperations(self):
        # Requesting FA information
        # ! [requestfaaliases]
        self.requestFA(FaDataTypeEnum.ALIASES)
        # ! [requestfaaliases]

        # ! [requestfagroups]
        self.requestFA(FaDataTypeEnum.GROUPS)
        # ! [requestfagroups]

        # ! [requestfaprofiles]
        self.requestFA(FaDataTypeEnum.PROFILES)
        # ! [requestfaprofiles]

        # Replacing FA information - Fill in with the appropriate XML string.
        # ! [replacefaonegroup]
        self.replaceFA(1000, FaDataTypeEnum.GROUPS, FaAllocationSamples.FaOneGroup)
        # ! [replacefaonegroup]

        # ! [replacefatwogroups]
        self.replaceFA(1001, FaDataTypeEnum.GROUPS, FaAllocationSamples.FaTwoGroups)
        # ! [replacefatwogroups]

        # ! [replacefaoneprofile]
        self.replaceFA(1002, FaDataTypeEnum.PROFILES, FaAllocationSamples.FaOneProfile)
        # ! [replacefaoneprofile]

        # ! [replacefatwoprofiles]
        self.replaceFA(1003, FaDataTypeEnum.PROFILES, FaAllocationSamples.FaTwoProfiles)
        # ! [replacefatwoprofiles]

        # ! [reqSoftDollarTiers]
        self.reqSoftDollarTiers(14001)
        # ! [reqSoftDollarTiers]

    def wshCalendarOperations(self):
        # ! [reqmetadata]
        self.reqWshMetaData(1100)
        # ! [reqmetadata]

        # ! [reqeventdata]
        wshEventData1 = WshEventData()
        wshEventData1.conId = 8314
        wshEventData1.startDate = "20220511"
        wshEventData1.totalLimit = 5
        self.reqWshEventData(1101, wshEventData1)
        # ! [reqeventdata]

        # ! [reqeventdata]
        wshEventData2 = WshEventData()
        wshEventData2.filter = "{\"watchlist\":[\"8314\"]}"
        wshEventData2.fillWatchlist = False
        wshEventData2.fillPortfolio = False
        wshEventData2.fillCompetitors = False
        wshEventData2.endDate = "20220512"
        self.reqWshEventData(1102, wshEventData2)
        # ! [reqeventdata]

    @iswrapper
    # ! [receivefa]
    def receiveFA(self, faData: FaDataType, cxml: str):
        super().receiveFA(faData, cxml)
        print("Receiving FA: ", faData)
        open('log/fa.xml', 'w').write(cxml)
    # ! [receivefa]

    @iswrapper
    # ! [softDollarTiers]
    def softDollarTiers(self, reqId: int, tiers: list):
        super().softDollarTiers(reqId, tiers)
        print("SoftDollarTiers. ReqId:", reqId)
        for tier in tiers:
            print("SoftDollarTier.", tier)
    # ! [softDollarTiers]

    @printWhenExecuting
    def miscelaneousOperations(self):
        # Request TWS' current time
        self.reqCurrentTime()
        # Setting TWS logging level
        self.setServerLogLevel(1)

    @printWhenExecuting
    def linkingOperations(self):
        # ! [querydisplaygroups]
        self.queryDisplayGroups(19001)
        # ! [querydisplaygroups]

        # ! [subscribetogroupevents]
        self.subscribeToGroupEvents(19002, 1)
        # ! [subscribetogroupevents]

        # ! [updatedisplaygroup]
        self.updateDisplayGroup(19002, "8314@SMART")
        # ! [updatedisplaygroup]

        # ! [subscribefromgroupevents]
        self.unsubscribeFromGroupEvents(19002)
        # ! [subscribefromgroupevents]

    @iswrapper
    # ! [displaygrouplist]
    def displayGroupList(self, reqId: int, groups: str):
        super().displayGroupList(reqId, groups)
        print("DisplayGroupList. ReqId:", reqId, "Groups", groups)
    # ! [displaygrouplist]

    @iswrapper
    # ! [displaygroupupdated]
    def displayGroupUpdated(self, reqId: int, contractInfo: str):
        super().displayGroupUpdated(reqId, contractInfo)
        print("DisplayGroupUpdated. ReqId:", reqId, "ContractInfo:", contractInfo)
    # ! [displaygroupupdated]

    @printWhenExecuting
    def whatIfOrderOperations(self):
    # ! [whatiflimitorder]
        whatIfOrder = OrderSamples.LimitOrder("SELL", 5, 70)
        whatIfOrder.whatIf = True
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), whatIfOrder)
    # ! [whatiflimitorder]
        time.sleep(2)

    @printWhenExecuting
    def orderOperations_req(self):
        # Requesting the next valid id
        # ! [reqids]
        # The parameter is always ignored.
        self.reqIds(-1)
        # ! [reqids]

        # Requesting all open orders
        # ! [reqallopenorders]
        self.reqAllOpenOrders()
        # ! [reqallopenorders]

        # Taking over orders to be submitted via TWS
        # ! [reqautoopenorders]
        self.reqAutoOpenOrders(True)
        # ! [reqautoopenorders]

        # Requesting this API client's orders
        # ! [reqopenorders]
        self.reqOpenOrders()
        # ! [reqopenorders]

        # Placing/modifying an order - remember to ALWAYS increment the
        # nextValidId after placing an order so it can be used for the next one!
        # Note if there are multiple clients connected to an account, the
        # order ID must also be greater than all order IDs returned for orders
        # to orderStatus and openOrder to this client.

        # ! [order_submission]
        self.simplePlaceOid = self.nextOrderId()
        self.placeOrder(self.simplePlaceOid, ContractSamples.USStock(),
                        OrderSamples.LimitOrder("SELL", 1, 50))
        # ! [order_submission]

        # ! [faorderoneaccount]
        faOrderOneAccount = OrderSamples.MarketOrder("BUY", 100)
        # Specify the Account Number directly
        faOrderOneAccount.account = "DU119915"
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(), faOrderOneAccount)
        # ! [faorderoneaccount]

        # ! [faordergroupequalquantity]
        faOrderGroupEQ = OrderSamples.LimitOrder("SELL", 200, 2000)
        faOrderGroupEQ.faGroup = "Group_Equal_Quantity"
        faOrderGroupEQ.faMethod = "EqualQuantity"
        self.placeOrder(self.nextOrderId(), ContractSamples.SimpleFuture(), faOrderGroupEQ)
        # ! [faordergroupequalquantity]

        # ! [faordergrouppctchange]
        faOrderGroupPC = OrderSamples.MarketOrder("BUY", 0)
        # You should not specify any order quantity for PctChange allocation method
        faOrderGroupPC.faGroup = "Pct_Change"
        faOrderGroupPC.faMethod = "PctChange"
        faOrderGroupPC.faPercentage = "100"
        self.placeOrder(self.nextOrderId(), ContractSamples.EurGbpFx(), faOrderGroupPC)
        # ! [faordergrouppctchange]

        # ! [faorderprofile]
        faOrderProfile = OrderSamples.LimitOrder("BUY", 200, 100)
        faOrderProfile.faProfile = "Percent_60_40"
        self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), faOrderProfile)
        # ! [faorderprofile]

        # ! [modelorder]
        modelOrder = OrderSamples.LimitOrder("BUY", 200, 100)
        modelOrder.account = "DF12345"
        modelOrder.modelCode = "Technology" # model for tech stocks first created in TWS
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(), modelOrder)
        # ! [modelorder]

        self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtBOX(),
                        OrderSamples.Block("BUY", 50, 20))
        self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtBOX(),
                         OrderSamples.BoxTop("SELL", 10))
        self.placeOrder(self.nextOrderId(), ContractSamples.FutureComboContract(),
                         OrderSamples.ComboLimitOrder("SELL", 1, 1, False))
        self.placeOrder(self.nextOrderId(), ContractSamples.StockComboContract(),
                          OrderSamples.ComboMarketOrder("BUY", 1, True))
        self.placeOrder(self.nextOrderId(), ContractSamples.OptionComboContract(),
                          OrderSamples.ComboMarketOrder("BUY", 1, False))
        self.placeOrder(self.nextOrderId(), ContractSamples.StockComboContract(),
                          OrderSamples.LimitOrderForComboWithLegPrices("BUY", 1, [10, 5], True))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                         OrderSamples.Discretionary("SELL", 1, 45, 0.5))
        self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtBOX(),
                          OrderSamples.LimitIfTouched("BUY", 1, 30, 34))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.LimitOnClose("SELL", 1, 34))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.LimitOnOpen("BUY", 1, 35))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.MarketIfTouched("BUY", 1, 30))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                         OrderSamples.MarketOnClose("SELL", 1))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.MarketOnOpen("BUY", 1))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.MarketOrder("SELL", 1))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.MarketToLimit("BUY", 1))
        self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtIse(),
                          OrderSamples.MidpointMatch("BUY", 1))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.MarketToLimit("BUY", 1))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.Stop("SELL", 1, 34.4))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.StopLimit("BUY", 1, 35, 33))
        self.placeOrder(self.nextOrderId(), ContractSamples.SimpleFuture(),
                          OrderSamples.StopWithProtection("SELL", 1, 45))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.SweepToFill("BUY", 1, 35))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.TrailingStop("SELL", 1, 0.5, 30))
        self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
                          OrderSamples.TrailingStopLimit("BUY", 1, 2, 5, 50))
        self.placeOrder(self.nextOrderId(), ContractSamples.USOptionContract(),
                         OrderSamples.Volatility("SELL", 1, 5, 2))

        self.bracketSample()

        self.conditionSamples()

        self.hedgeSample()

        # NOTE: the following orders are not supported for Paper Trading
        # self.placeOrder(self.nextOrderId(), ContractSamples.USStock(), OrderSamples.AtAuction("BUY", 100, 30.0))
        # self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtBOX(), OrderSamples.AuctionLimit("SELL", 10, 30.0, 2))
        # self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtBOX(), OrderSamples.AuctionPeggedToStock("BUY", 10, 30, 0.5))
        # self.placeOrder(self.nextOrderId(), ContractSamples.OptionAtBOX(), OrderSamples.AuctionRelative("SELL", 10, 0.6))
        # self.placeOrder(self.nextOrderId(), ContractSamples.SimpleFuture(), OrderSamples.MarketWithProtection("BUY", 1))
        # self.placeOrder(self.nextOrderId(), ContractSamples.USStock(), OrderSamples.PassiveRelative("BUY", 1, 0.5))

        # 208813720 (GOOG)
        # self.placeOrder(self.nextOrderId(), ContractSamples.USStock(),
        #    OrderSamples.PeggedToBenchmark("SELL", 100, 33, True, 0.1, 1, 208813720, "ARCA", 750, 650, 800))

        # STOP ADJUSTABLE ORDERS
        # Order stpParent = OrderSamples.Stop("SELL", 100, 30)
        # stpParent.OrderId = self.nextOrderId()
        # self.placeOrder(stpParent.OrderId, ContractSamples.EuropeanStock(), stpParent)
        # self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), OrderSamples.AttachAdjustableToStop(stpParent, 35, 32, 33))
        # self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), OrderSamples.AttachAdjustableToStopLimit(stpParent, 35, 33, 32, 33))
        # self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), OrderSamples.AttachAdjustableToTrail(stpParent, 35, 32, 32, 1, 0))

        # Order lmtParent = OrderSamples.LimitOrder("BUY", 100, 30)
        # lmtParent.OrderId = self.nextOrderId()
        # self.placeOrder(lmtParent.OrderId, ContractSamples.EuropeanStock(), lmtParent)
        # Attached TRAIL adjusted can only be attached to LMT parent orders.
        # self.placeOrder(self.nextOrderId(), ContractSamples.EuropeanStock(), OrderSamples.AttachAdjustableToTrailAmount(lmtParent, 34, 32, 33, 0.008))
        self.algoSamples()
        
        self.ocaSample()

        # Request the day's executions
        # ! [reqexecutions]
        self.reqExecutions(10001, ExecutionFilter())
        # ! [reqexecutions]
        
        # Requesting completed orders
        # ! [reqcompletedorders]
        self.reqCompletedOrders(False)
        # ! [reqcompletedorders]
        
        # Placing crypto order
        # ! [cryptoplaceorder]
        self.placeOrder(self.nextOrderId(), ContractSamples.CryptoContract(), OrderSamples.LimitOrder("BUY", Decimal("0.00001234"), 3370))
        # ! [cryptoplaceorder]
        

        # Placing limit order with manual order time
        # ! [place_order_with_manual_order_time]
        self.placeOrder(self.nextOrderId(), ContractSamples.USStockAtSmart(), OrderSamples.LimitOrderWithManualOrderTime("BUY", Decimal("100"), 111.11, "20220314-13:00:00"))
        # ! [place_order_with_manual_order_time]

        # Placing peg best up to mid order
        # ! [place_peg_best_up_to_mid_order]
        self.placeOrder(self.nextOrderId(), ContractSamples.IBKRATSContract(), OrderSamples.PegBestUpToMidOrder("BUY", Decimal("100"), 111.11, 100, 200, 0.02, 0.025))
        # ! [place_peg_best_up_to_mid_order]

        # Placing peg best order
        # ! [place_peg_best_order]
        self.placeOrder(self.nextOrderId(), ContractSamples.IBKRATSContract(), OrderSamples.PegBestOrder("BUY", Decimal("100"), 111.11, 100, 200, 0.03))
        # ! [place_peg_best_order]

        # Placing peg mid order
        # ! [place_peg_mid_order]
        self.placeOrder(self.nextOrderId(), ContractSamples.IBKRATSContract(), OrderSamples.PegMidOrder("BUY", Decimal("100"), 111.11, 100, 0.02, 0.025))
        # ! [place_peg_mid_order]

    def orderOperations_cancel(self):
        if self.simplePlaceOid is not None:
            # ! [cancelorder]
            self.cancelOrder(self.simplePlaceOid, "")
            # ! [cancelorder]
            
        # Cancel all orders for all accounts
        # ! [reqglobalcancel]
        self.reqGlobalCancel()
        # ! [reqglobalcancel]
         
        # Cancel limit order with manual order cancel time
        if self.simplePlaceOid is not None:
            # ! [cancel_order_with_manual_order_time]
            self.cancelOrder(self.simplePlaceOid, "20220303-13:00:00")
            # ! [cancel_order_with_manual_order_time]

    def rerouteCFDOperations(self):
        # ! [reqmktdatacfd]
        self.reqMktData(16001, ContractSamples.USStockCFD(), "", False, False, [])
        self.reqMktData(16002, ContractSamples.EuropeanStockCFD(), "", False, False, []);
        self.reqMktData(16003, ContractSamples.CashCFD(), "", False, False, []);
        # ! [reqmktdatacfd]

        # ! [reqmktdepthcfd]
        self.reqMktDepth(16004, ContractSamples.USStockCFD(), 10, False, []);
        self.reqMktDepth(16005, ContractSamples.EuropeanStockCFD(), 10, False, []);
        self.reqMktDepth(16006, ContractSamples.CashCFD(), 10, False, []);
        # ! [reqmktdepthcfd]

    def marketRuleOperations(self):
        self.reqContractDetails(17001, ContractSamples.USStock())
        self.reqContractDetails(17002, ContractSamples.Bond())

        # ! [reqmarketrule]
        self.reqMarketRule(26)
        self.reqMarketRule(239)
        # ! [reqmarketrule]
        
    def ibkratsSample(self):
        # ! [ibkratssubmit]
        ibkratsOrder = OrderSamples.LimitIBKRATS("BUY", 100, 330)
        self.placeOrder(self.nextOrderId(), ContractSamples.IBKRATSContract(), ibkratsOrder)
        # ! [ibkratssubmit]

    @iswrapper
    # ! [execdetails]
    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        super().execDetails(reqId, contract, execution)
        print("ExecDetails. ReqId:", reqId, "Symbol:", contract.symbol, "SecType:", contract.secType, "Currency:", contract.currency, execution)
    # ! [execdetails]

    @iswrapper
    # ! [execdetailsend]
    def execDetailsEnd(self, reqId: int):
        super().execDetailsEnd(reqId)
        print("ExecDetailsEnd. ReqId:", reqId)
    # ! [execdetailsend]

    @iswrapper
    # ! [commissionreport]
    def commissionReport(self, commissionReport: CommissionReport):
        super().commissionReport(commissionReport)
        print("CommissionReport.", commissionReport)
    # ! [commissionreport]

    @iswrapper
    # ! [currenttime]
    def currentTime(self, time:int):
        super().currentTime(time)
        print("CurrentTime:", datetime.datetime.fromtimestamp(time).strftime("%Y%m%d-%H:%M:%S"))
    # ! [currenttime]

    @iswrapper
    # ! [completedorder]
    def completedOrder(self, contract: Contract, order: Order,
                  orderState: OrderState):
        super().completedOrder(contract, order, orderState)
        print("CompletedOrder. PermId:", intMaxString(order.permId), "ParentPermId:", longMaxString(order.parentPermId), "Account:", order.account, 
              "Symbol:", contract.symbol, "SecType:", contract.secType, "Exchange:", contract.exchange, 
              "Action:", order.action, "OrderType:", order.orderType, "TotalQty:", decimalMaxString(order.totalQuantity), 
              "CashQty:", floatMaxString(order.cashQty), "FilledQty:", decimalMaxString(order.filledQuantity), 
              "LmtPrice:", floatMaxString(order.lmtPrice), "AuxPrice:", floatMaxString(order.auxPrice), "Status:", orderState.status,
              "Completed time:", orderState.completedTime, "Completed Status:" + orderState.completedStatus,
              "MinTradeQty:", intMaxString(order.minTradeQty), "MinCompeteSize:", intMaxString(order.minCompeteSize),
              "competeAgainstBestOffset:", "UpToMid" if order.competeAgainstBestOffset == COMPETE_AGAINST_BEST_OFFSET_UP_TO_MID else floatMaxString(order.competeAgainstBestOffset),
              "MidOffsetAtWhole:", floatMaxString(order.midOffsetAtWhole),"MidOffsetAtHalf:" ,floatMaxString(order.midOffsetAtHalf))
    # ! [completedorder]

    @iswrapper
    # ! [completedordersend]
    def completedOrdersEnd(self):
        super().completedOrdersEnd()
        print("CompletedOrdersEnd")
    # ! [completedordersend]

    @iswrapper
    # ! [replacefaend]
    def replaceFAEnd(self, reqId: int, text: str):
        super().replaceFAEnd(reqId, text)
        print("ReplaceFAEnd.", "ReqId:", reqId, "Text:", text)
    # ! [replacefaend]

    @iswrapper
    # ! [wshmetadata]
    def wshMetaData(self, reqId: int, dataJson: str):
        super().wshMetaData(reqId, dataJson)
        print("WshMetaData.", "ReqId:", reqId, "Data JSON:", dataJson)
    # ! [wshmetadata]

    @iswrapper
    # ! [wsheventdata]
    def wshEventData(self, reqId: int, dataJson: str):
        super().wshEventData(reqId, dataJson)
        print("WshEventData.", "ReqId:", reqId, "Data JSON:", dataJson)
    # ! [wsheventdata]

    @iswrapper
    # ! [historicalschedule]
    def historicalSchedule(self, reqId: int, startDateTime: str, endDateTime: str, timeZone: str, sessions: ListOfHistoricalSessions):
        super().historicalSchedule(reqId, startDateTime, endDateTime, timeZone, sessions)
        print("HistoricalSchedule. ReqId:", reqId, "Start:", startDateTime, "End:", endDateTime, "TimeZone:", timeZone)

        for session in sessions:
            print("\tSession. Start:", session.startDateTime, "End:", session.endDateTime, "Ref Date:", session.refDate)
    # ! [historicalschedule]

    @iswrapper
    # ! [userinfo]
    def userInfo(self, reqId: int, whiteBrandingId: str):
        super().userInfo(reqId, whiteBrandingId)
        print("UserInfo.", "ReqId:", reqId, "WhiteBrandingId:", whiteBrandingId)
    # ! [userinfo]

class ESDynamicStraddleStrategy(Object):
    def __init__(self,testapp):
        EScontract = Contract()
        EScontract.symbol = "ES"
        EScontract.secType = "FUT"
        EScontract.exchange = "CME"
        EScontract.currency = "USD"
        EScontract.lastTradeDateOrContractMonth = "202406"

        self.EScontract = EScontract
        self.lastESPrice = None
        self.currentESPrice = None
        self.priceDirection = None #1 for up, -1 for down, 0 for no change
        self.testapp = testapp
        
        self.OptionTradeDate = "20240418"
        self.short_call_option_positions = {}  #key is strike, value is position
        self.long_call_option_positions = {} #key is strike, value is position
        self.short_put_option_positions = {}  #key is strike, value is position
        self.long_put_option_positions = {} #key is strike, value is position
        self.short_call_option_avgcost = {}  #key is strike, value is avgcost
        self.long_call_option_avgcost = {} #key is strike, value is avgcost
        self.short_put_option_avgcost = {}  #key is strike, value is avgcost
        self.long_put_option_avgcost = {} #key is strike, value is avgcost
        self.futures_positions = []
        self.ES_FOP_quote_bid_call = {}
        self.ES_FOP_quote_bid_put = {}
        self.ES_FOP_quote_ask_call = {}
        self.ES_FOP_quote_ask_put = {}
        self.transmit_orders = True
        self.place_orders_to_account = "U3642202"
        self.log_file = "ESDynamicStraddleStrategy_" + self.OptionTradeDate + "_.log"
        self.log_file_handle = open(self.log_file, "a")
        self.log_file_handle.write("##############################################################################\n")
        self.log_file_handle.write("ESDynamicStraddleStrategy started at " + str(datetime.datetime.now()) + "\n")
        self.limit_price_slack_ticks = 6
        self.hedge_outer_offset = 200
        self.intra_order_sleep_time_ms = 100
        self.attach_bracket_order = True
        self.call_stplmt_profit_open_orders_tuples = {} #key is strike, value is (order_id, contract, order, order_state)
        self.put_stplmt_profit_open_orders_tuples = {} #key is strike, value is (order_id, contract, order, order_state)
        self.call_stplmt_open_orders_tuples = {} #key is strike, value is (order_id, contract, order, order_state)
        self.put_stplmt_open_orders_tuples = {} #key is strike, value is (order_id, contract, order, order_state)
        #self.call_bracket_order_maintenance_on_hold = False
        #self.put_bracket_order_maintenance_on_hold = False
        self.call_bracket_order_maintenance_on_hold_for_strike = {} #key is strike, value is True/False
        self.put_bracket_order_maintenance_on_hold_for_strike = {} #key is strike, value is True/False
        self.call_bracket_profit_order_maintenance_on_hold_for_strike = {} #key is strike, value is order_id
        self.put_bracket_profit_order_maintenance_on_hold_for_strike = {} #key is strike, value is order_id
        self.profit_target_divisor = 10
        self.stop_loss_increment = 5
        self.stop_limit_increment = 10
        self.es_contract_multiplier = 50

    def updateESFOPPrice(self, reqContract, tickType, price, attrib):
        assert reqContract.symbol == "ES" and reqContract.secType == "FOP" and reqContract.lastTradeDateOrContractMonth == self.OptionTradeDate
        if reqContract.right == "C":
            if tickType == TickTypeEnum.BID:
                self.ES_FOP_quote_bid_call[reqContract.strike] = price
            elif tickType == TickTypeEnum.ASK:
                self.ES_FOP_quote_ask_call[reqContract.strike] = price
        elif reqContract.right == "P":
            if tickType == TickTypeEnum.BID:
                self.ES_FOP_quote_bid_put[reqContract.strike] = price
            elif tickType == TickTypeEnum.ASK:
                self.ES_FOP_quote_ask_put[reqContract.strike] = price

    def subscribePositions(self, testapp : TestApp):
        testapp.reqAccountUpdates(True, testapp.account)
        testapp.reqPositions()


    def subscribeToMarketData(self, reqId, testapp : TestApp):
        #get new reqId
        #reqId = self.nextOrderId()
        print("subscribeToMarketData called with reqId:", reqId, "EScontract:", self.EScontract)
        self.log_file_handle.write("subscribeToMarketData called with reqId:" + str(reqId) + " EScontract:" + str(self.EScontract) + "\n")
        testapp.MktDataRequest[reqId] = self.EScontract
        testapp.reqMarketDataType(1)
        testapp.reqMktData(reqId, self.EScontract, "", False, False, [])

    def process_messages_from_ib_queue(self, testapp : TestApp):
        while not testapp.message_from_ib_queue.empty():
            msg = testapp.message_from_ib_queue.get()
            #msg is a tuple with the first e`lement being the message type and the remaining elements being the message
            msg_type = msg[0]
            if msg_type == "position":
                account = msg[1]
                contract = msg[2]
                position = msg[3]
                avgCost = msg[4]
                print("position message received. account:", account, "contract:", contract, "position:", position, "avgCost:", avgCost)
                self.log_file_handle.write("position message received. account:" + str(account) + " contract:" + str(contract) + " position:" + str(position) + " avgCost:" + str(avgCost) + "\n")
                if contract.symbol == "ES" and contract.secType == "FOP" and contract.lastTradeDateOrContractMonth == self.OptionTradeDate:
                    if position > 0:
                        if contract.right == "C":
                            self.long_call_option_positions[contract.strike] = position
                            self.long_call_option_avgcost[contract.strike] = avgCost
                        elif contract.right == "P":
                            self.long_put_option_positions[contract.strike] = position
                            self.long_put_option_avgcost[contract.strike] = avgCost
                    elif position < 0:
                        if contract.right == "C":
                            self.short_call_option_positions[contract.strike] = position
                            self.short_call_option_avgcost[contract.strike] = avgCost
                        elif contract.right == "P":
                            self.short_put_option_positions[contract.strike] = position
                            self.short_put_option_avgcost[contract.strike] = avgCost
                    elif position == 0:
                        if contract.right == "C":
                            if contract.strike in self.long_call_option_positions:
                                del self.long_call_option_positions[contract.strike]
                                del self.long_call_option_avgcost[contract.strike]
                            if contract.strike in self.short_call_option_positions:
                                del self.short_call_option_positions[contract.strike]
                                del self.short_call_option_avgcost[contract.strike]
                        elif contract.right == "P":
                            if contract.strike in self.long_put_option_positions:
                                del self.long_put_option_positions[contract.strike]
                                del self.long_put_option_avgcost[contract.strike]
                            if contract.strike in self.short_put_option_positions:
                                del self.short_put_option_positions[contract.strike]
                                del self.short_put_option_avgcost[contract.strike]
                #print updated positions
                print("long_call_option_positions:", self.long_call_option_positions, "long_call_option_avgcost:", self.long_call_option_avgcost)
                self.log_file_handle.write("long_call_option_positions:" + str(self.long_call_option_positions) + "long_call_option_avgcost:" + str(self.long_call_option_avgcost) + "\n")
                print("short_call_option_positions:", self.short_call_option_positions, "short_call_option_avgcost:", self.short_call_option_avgcost)
                self.log_file_handle.write("short_call_option_positions:" + str(self.short_call_option_positions) + "short_call_option_avgcost:" + str(self.short_call_option_avgcost) + "\n")
                print("long_put_option_positions:", self.long_put_option_positions, "long_put_option_avgcost:", self.long_put_option_avgcost)
                self.log_file_handle.write("long_put_option_positions:" + str(self.long_put_option_positions) + "long_put_option_avgcost:" + str(self.long_put_option_avgcost) + "\n")
                print("short_put_option_positions:", self.short_put_option_positions, "short_put_option_avgcost:", self.short_put_option_avgcost)
                self.log_file_handle.write("short_put_option_positions:" + str(self.short_put_option_positions) + "short_put_option_avgcost:" + str(self.short_put_option_avgcost) + "\n")
            elif msg_type == "open_order":
                order_id = msg[1]
                contract = msg[2]
                order = msg[3]
                order_state = msg[4]
                print("open_order message received. order_id:", order_id, "contract:", contract, "order:", order, "order_state:", order_state)
                self.log_file_handle.write("open_order message received. order_id:" + str(order_id) + " contract:" + str(contract) + " order:" + str(order) + " order_state:" + str(order_state) + "\n")
                if contract.symbol == "ES" and contract.secType == "FOP" and contract.lastTradeDateOrContractMonth == self.OptionTradeDate:
                    if order.action == "BUY" and order.orderType == "STP LMT" and order.lmtPrice is not None and order.lmtPrice > 0 and order.auxPrice is not None and order.auxPrice > 0 and order_state.status == "PreSubmitted":
                        if contract.right == "C":
                            if contract.strike not in self.call_stplmt_open_orders_tuples:
                                self.call_stplmt_open_orders_tuples[contract.strike] = []
                            self.call_stplmt_open_orders_tuples[contract.strike] = ((order_id, contract, order, order_state))
                            self.call_bracket_order_maintenance_on_hold_for_strike[contract.strike] = False
                        elif contract.right == "P":
                            if contract.strike not in self.put_stplmt_open_orders_tuples:
                                self.put_stplmt_open_orders_tuples[contract.strike] = []
                            self.put_stplmt_open_orders_tuples[contract.strike] = ((order_id, contract, order, order_state))
                            self.put_bracket_order_maintenance_on_hold_for_strike[contract.strike] = False

                    if order.action == "BUY" and order.orderType == "LMT" and order_state.status == "Submitted" and order.lmtPrice is not None and order.lmtPrice > 0:
                        if contract.right == "C":
                            if contract.strike not in self.call_stplmt_profit_open_orders_tuples:
                                self.call_stplmt_profit_open_orders_tuples[contract.strike] = []
                            self.call_stplmt_profit_open_orders_tuples[contract.strike] = ((order_id, contract, order, order_state))
                            self.call_bracket_profit_order_maintenance_on_hold_for_strike[contract.strike] = False
                        elif contract.right == "P":
                            if contract.strike not in self.put_stplmt_profit_open_orders_tuples:
                                self.put_stplmt_profit_open_orders_tuples[contract.strike] = []
                            self.put_stplmt_profit_open_orders_tuples[contract.strike] = ((order_id, contract, order, order_state))
                            self.put_bracket_profit_order_maintenance_on_hold_for_strike[contract.strike] = False
    
        #request currently open orders
        testapp.reqAllOpenOrders()

    def cancelpendingstplmtorder(self, testapp : TestApp, strike, right):
        #get current time in YYYYMMDD-HH:MM:SS format
        current_time = datetime.datetime.now().strftime("%Y%m%d-%H:%M:%S")
        if right == "C":
            if strike in self.call_stplmt_open_orders_tuples:
                strike, stplmt_open_orders_tuples = self.call_stplmt_open_orders_tuples.items()
                for order_id, contract, order, order_state in stplmt_open_orders_tuples:
                    testapp.cancelOrder(order_id,current_time)
                    #remove the order from the list
                    self.call_stplmt_open_orders_tuples[strike].remove((order_id, contract, order, order_state))
        else:
            if strike in self.put_stplmt_open_orders_tuples:
                strike, stplmt_open_orders_tuples = self.put_stplmt_open_orders_tuples.items()
                for order_id, contract, order, order_state in stplmt_open_orders_tuples:
                    testapp.cancelOrder(order_id, current_time)
                    #remove the order from the list
                    self.put_stplmt_open_orders_tuples[strike].remove((order_id, contract, order, order_state))
    def cancelpendingstplmtprofitorder(self, testapp : TestApp, strike, right):
        #get current time in YYYYMMDD-HH:MM:SS format
        current_time = datetime.datetime.now().strftime("%Y%m%d-%H:%M:%S")
        if right == "C":
            if strike in self.call_stplmt_profit_open_orders_tuples:
                strike, stplmt_profit_open_orders_tuples = self.call_stplmt_profit_open_orders_tuples.items()
                for order_id, contract, order, order_state in stplmt_profit_open_orders_tuples:
                    testapp.cancelOrder(order_id,current_time)
                    #remove the order from the list
                    self.call_stplmt_profit_open_orders_tuples[strike].remove((order_id, contract, order, order_state))
        else:
            if strike in self.put_stplmt_profit_open_orders_tuples:
                strike, stplmt_profit_open_orders_tuples = self.put_stplmt_profit_open_orders_tuples.items()
                for order_id, contract, order, order_state in stplmt_profit_open_orders_tuples:
                    testapp.cancelOrder(order_id, current_time)
                    #remove the order from the list
                    self.put_stplmt_profit_open_orders_tuples[strike].remove((order_id, contract, order, order_state))

    def sanity_check_and_maintenanace(self, testapp : TestApp, newESPrice):
        #return
        #this function enforces the following rules:
        #1. every position should have a bracket order in place
        #2. every bracket order should have a corresponding position

        #get current time in YYYYMMDD-HH:MM:SS format
        current_time = datetime.datetime.now().strftime("%Y%m%d-%H:%M:%S")
        #1. check whether every short position has a bracket order in place
        for strike, position in self.short_call_option_positions.items():
            strike_call_bracket_order_stplmt_quantity = 0
            strike_call_bracket_order_profit_quantity = 0
            if (strike in self.call_bracket_order_maintenance_on_hold_for_strike) and self.call_bracket_order_maintenance_on_hold_for_strike[strike] == True:
                print("call bracket order maintenance on hold for strike:", strike)
                self.log_file_handle.write("call bracket order maintenance on hold for strike:" + str(strike) + "\n")
                continue
            if (strike in self.call_bracket_profit_order_maintenance_on_hold_for_strike) and self.call_bracket_profit_order_maintenance_on_hold_for_strike[strike] == True:
                print("call bracket profit order maintenance on hold for strike:", strike)
                self.log_file_handle.write("call bracket profit order maintenance on hold for strike:" + str(strike) + "\n")
                continue

            if strike in self.call_stplmt_open_orders_tuples:
                if strike in self.call_stplmt_profit_open_orders_tuples:
                    order_id, contract, order, order_state = self.call_stplmt_open_orders_tuples[strike]
                    strike_call_bracket_order_stplmt_quantity = strike_call_bracket_order_stplmt_quantity  + order.totalQuantity
            if strike in self.call_stplmt_profit_open_orders_tuples:
                if strike in self.call_stplmt_profit_open_orders_tuples:
                    order_id, contract, order, order_state = self.call_stplmt_profit_open_orders_tuples[strike]
                    strike_call_bracket_order_profit_quantity = strike_call_bracket_order_profit_quantity + order.totalQuantity
            if -position > strike_call_bracket_order_stplmt_quantity:
                needed_quantity = -position - strike_call_bracket_order_stplmt_quantity
                #create a bracket order for this position
                position_price =  self.short_call_option_avgcost[strike]/self.es_contract_multiplier
                call_profit_order_target_price = position_price/self.profit_target_divisor
                if call_profit_order_target_price >= 10:
                    call_profit_order_target_price = round(call_profit_order_target_price * 4) / 4
                else:
                    call_profit_order_target_price = round(call_profit_order_target_price * 20) / 20
                call_stop_order_stop_price = position_price + self.stop_loss_increment
                if call_stop_order_stop_price >= 10:
                    call_stop_order_stop_price = round(call_stop_order_stop_price * 4) / 4
                else:
                    call_stop_order_stop_price = round(call_stop_order_stop_price * 20) / 20
                call_stop_order_stop_limit_price = call_stop_order_stop_price + self.stop_limit_increment
                if call_stop_order_stop_limit_price >= 10:
                    call_stop_order_stop_limit_price = round(call_stop_order_stop_limit_price * 4) / 4
                else:
                    call_stop_order_stop_limit_price = round(call_stop_order_stop_limit_price * 20) / 20

                call_contract = Contract()
                call_contract.symbol = "ES"
                call_contract.secType = "FOP"
                call_contract.exchange = "CME"
                call_contract.currency = "USD"
                call_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                call_contract.right = "C"
                call_contract.multiplier = str(self.es_contract_multiplier)
                call_contract.strike = strike
                call_profit_order = Order()
                call_profit_order.action = "BUY"
                call_profit_order.orderType = "LMT"
                call_profit_order.totalQuantity = needed_quantity
                call_profit_order.lmtPrice = call_profit_order_target_price
                call_profit_order.transmit = self.transmit_orders
                call_stop_order = Order()
                call_stop_order.action = "BUY"
                call_stop_order.orderType = "STP LMT"
                call_stop_order.totalQuantity = needed_quantity
                call_stop_order.auxPrice = call_stop_order_stop_price
                call_stop_order.lmtPrice = call_stop_order_stop_limit_price
                call_stop_order.transmit = self.transmit_orders

                call_profit_order.account = self.place_orders_to_account
                call_stop_order.account = self.place_orders_to_account
                call_profit_order.outsideRth = True
                call_stop_order.outsideRth = True
                call_profit_order.triggerMethod = 1
                call_stop_order.triggerMethod = 1
                call_bracket_OCA_orders = [call_profit_order, call_stop_order]
                OrderSamples.OneCancelsAll("AttachBracketCallOCO_"+str(testapp.nextValidOrderId), call_bracket_OCA_orders, 2)
                for o in call_bracket_OCA_orders:
                    o.account = self.place_orders_to_account
                    testapp.placeOrder(testapp.nextValidOrderId, call_contract, o)
                    testapp.nextValidOrderId += 1
                
                print("position:", position, "strike_call_bracket_order_stplmt_quantity:", strike_call_bracket_order_stplmt_quantity, "needed_quantity:", needed_quantity)
                self.log_file_handle.write("position:" + str(position) + "strike_call_bracket_order_stplmt_quantity:" + str(strike_call_bracket_order_stplmt_quantity) + "needed_quantity:" + str(needed_quantity) + "\n")
                self.log_file_handle.write("Not enough bracket orders: attaching call order for strike:" + str(strike) + "limit_price:" + str(call_profit_order_target_price) + "call_contract:" + str(call_contract) + "profit_order:" + str(call_profit_order) + "loss_order:" + str(call_stop_order) + "\n")
                time.sleep(self.intra_order_sleep_time_ms/1000)
                self.call_bracket_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
                self.call_bracket_profit_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
            elif -position < strike_call_bracket_order_stplmt_quantity:
                needed_quantity = strike_call_bracket_order_stplmt_quantity + position
                #cancel the extra bracket order
                self.cancelpendingstplmtorder(testapp, strike, "C")
                print("position:", position, "strike_call_bracket_order_stplmt_quantity:", strike_call_bracket_order_stplmt_quantity, "needed_quantity:", needed_quantity)
                self.log_file_handle.write("position:" + str(position) + "strike_call_bracket_order_stplmt_quantity:" + str(strike_call_bracket_order_stplmt_quantity) + "needed_quantity:" + str(needed_quantity) + "\n")
                print("Too many bracket orders: cancelling call order for strike:", strike)
                self.log_file_handle.write("Too many bracket orders: cancelling call order for strike:" + str(strike) + "\n")
                time.sleep(self.intra_order_sleep_time_ms/1000)
                self.call_bracket_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
                self.call_bracket_profit_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
            elif -position == strike_call_bracket_order_stplmt_quantity:
                #check that bracket order limit order and stop limit orders have same quantity
                if strike_call_bracket_order_stplmt_quantity != strike_call_bracket_order_profit_quantity:
                    #cancel the extra bracket order
                    self.cancelpendingstplmtorder(testapp, strike, "C")
                    self.cancelpendingstplmtprofitorder(testapp, strike, "C")
                    print("position:", position, "strike_call_bracket_order_stplmt_quantity:", strike_call_bracket_order_stplmt_quantity, "strike_call_bracket_order_profit_quantity:", strike_call_bracket_order_profit_quantity)
                    self.log_file_handle.write("position:" + str(position) + "strike_call_bracket_order_stplmt_quantity:" + str(strike_call_bracket_order_stplmt_quantity) + "strike_call_bracket_order_profit_quantity:" + str(strike_call_bracket_order_profit_quantity) + "\n")
                    print("Unequal bracket profit and stplmt legs: cancelling call profit and loss orders for strike:", strike)
                    self.log_file_handle.write("Unequal bracket profit and stplmt legs: cancelling call profit and loss orders for strike:" + str(strike) + "\n")
                    time.sleep(self.intra_order_sleep_time_ms/1000)
                    self.call_bracket_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
                    self.call_bracket_profit_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset

        #now do the same for put positions
        for strike, position in self.short_put_option_positions.items():
            strike_put_bracket_order_stplmt_quantity = 0
            strike_put_bracket_order_profit_quantity = 0
            if (strike in self.put_bracket_order_maintenance_on_hold_for_strike) and self.put_bracket_order_maintenance_on_hold_for_strike[strike] == True:
                print("put bracket order maintenance on hold for strike:", strike)
                self.log_file_handle.write("put bracket order maintenance on hold for strike:" + str(strike) + "\n")
                continue
            if (strike in self.put_bracket_profit_order_maintenance_on_hold_for_strike) and self.put_bracket_profit_order_maintenance_on_hold_for_strike[strike] == True:
                print("put bracket profit order maintenance on hold for strike:", strike)
                self.log_file_handle.write("put bracket profit order maintenance on hold for strike:" + str(strike) + "\n")
                continue

            if strike in self.put_stplmt_open_orders_tuples:
                if strike in self.put_stplmt_open_orders_tuples:
                    order_id, contract, order, order_state = self.put_stplmt_open_orders_tuples[strike]
                strike_put_bracket_order_stplmt_quantity = strike_put_bracket_order_stplmt_quantity  + order.totalQuantity
            if strike in self.put_stplmt_profit_open_orders_tuples:
                if strike in self.put_stplmt_profit_open_orders_tuples:
                    order_id, contract, order, order_state in self.put_stplmt_profit_open_orders_tuples[strike]
                    strike_put_bracket_order_profit_quantity = strike_put_bracket_order_profit_quantity + order.totalQuantity

            if -position > strike_put_bracket_order_stplmt_quantity:
                needed_quantity = -position - strike_put_bracket_order_stplmt_quantity
                #create a bracket order for this position
                position_price =  self.short_put_option_avgcost[strike]/self.es_contract_multiplier
                put_profit_order_target_price = position_price/self.profit_target_divisor
                if put_profit_order_target_price >= 10:
                    put_profit_order_target_price = round(put_profit_order_target_price * 4) / 4
                else:
                    put_profit_order_target_price = round(put_profit_order_target_price * 20) / 20
                put_stop_order_stop_price = position_price + self.stop_loss_increment
                if put_stop_order_stop_price >= 10:
                    put_stop_order_stop_price = round(put_stop_order_stop_price * 4) / 4
                else:
                    put_stop_order_stop_price = round(put_stop_order_stop_price * 20) / 20
                put_stop_order_stop_limit_price = put_stop_order_stop_price + self.stop_limit_increment
                if put_stop_order_stop_limit_price >= 10:
                    put_stop_order_stop_limit_price = round(put_stop_order_stop_limit_price * 4) / 4
                else:
                    put_stop_order_stop_limit_price = round(put_stop_order_stop_limit_price * 20) / 20

                put_contract = Contract()
                put_contract.symbol = "ES"
                put_contract.secType = "FOP"
                put_contract.exchange = "CME"
                put_contract.currency = "USD"
                put_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                put_contract.right = "P"
                put_contract.multiplier = str(self.es_contract_multiplier)
                put_contract.strike = strike
                put_profit_order = Order()
                put_profit_order.action = "BUY"
                put_profit_order.orderType = "LMT"
                put_profit_order.totalQuantity = needed_quantity
                put_profit_order.lmtPrice = put_profit_order_target_price
                put_profit_order.transmit = self.transmit_orders
                put_stop_order = Order()
                put_stop_order.action = "BUY"
                put_stop_order.orderType = "STP LMT"
                put_stop_order.totalQuantity = needed_quantity
                put_stop_order.auxPrice = put_stop_order_stop_price
                put_stop_order.lmtPrice = put_stop_order_stop_limit_price
                put_stop_order.transmit = self.transmit_orders

                put_profit_order.account = self.place_orders_to_account
                put_stop_order.account = self.place_orders_to_account
                put_profit_order.outsideRth = True
                put_stop_order.outsideRth = True
                put_profit_order.triggerMethod = 1
                put_stop_order.triggerMethod = 1
                put_bracket_OCA_orders = [put_profit_order, put_stop_order]
                OrderSamples.OneCancelsAll("AttachBracketPutOCO_"+str(testapp.nextValidOrderId), put_bracket_OCA_orders, 2)
                for o in put_bracket_OCA_orders:
                    o.account = self.place_orders_to_account
                    testapp.placeOrder(testapp.nextValidOrderId, put_contract, o)
                    testapp.nextValidOrderId += 1
                
                print("position:", position, "strike_put_bracket_order_stplmt_quantity:", strike_put_bracket_order_stplmt_quantity, "needed_quantity:", needed_quantity)
                self.log_file_handle.write("position:" + str(position) + "strike_put_bracket_order_stplmt_quantity:" + str(strike_put_bracket_order_stplmt_quantity) + "needed_quantity:" + str(needed_quantity) + "\n")
                print("Not enough bracket orders: attaching put order for strike:", strike, "limit_price:", put_profit_order_target_price, "put_contract:", put_contract, "profit_order:", put_profit_order, "loss_order:", put_stop_order)
                self.log_file_handle.write("Not enough bracket orders: attaching put order for strike:" + str(strike) + "limit_price:" + str(put_profit_order_target_price) + "put_contract:" + str(put_contract) + "profit_order:" + str(put_profit_order) + "loss_order:" + str(put_stop_order) + "\n")
                time.sleep(self.intra_order_sleep_time_ms/1000)
                self.put_bracket_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
                self.put_bracket_profit_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
            elif -position < strike_put_bracket_order_stplmt_quantity:
                needed_quantity = strike_put_bracket_order_stplmt_quantity + position
                #cancel the extra bracket order
                self.cancelpendingstplmtorder(testapp, strike, "P")
                print("position:", position, "strike_put_bracket_order_stplmt_quantity:", strike_put_bracket_order_stplmt_quantity, "needed_quantity:", needed_quantity)
                self.log_file_handle.write("position:" + str(position) + "strike_put_bracket_order_stplmt_quantity:" + str(strike_put_bracket_order_stplmt_quantity) + "needed_quantity:" + str(needed_quantity) + "\n")
                print("Too many bracket orders: cancelling put order for strike:", strike)
                self.log_file_handle.write("Too many bracket orders: cancelling put order for strike:" + str(strike) + "\n")
                time.sleep(self.intra_order_sleep_time_ms/1000)
                self.put_bracket_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
                self.put_bracket_profit_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
            elif -position == strike_put_bracket_order_stplmt_quantity:
                #check that bracket order limit order and stop limit orders have same quantity
                if strike_put_bracket_order_stplmt_quantity != strike_put_bracket_order_profit_quantity:
                    #cancel the extra bracket order
                    self.cancelpendingstplmtorder(testapp, strike, "P")
                    self.cancelpendingstplmtprofitorder(testapp, strike, "P")
                    print("position:", position, "strike_put_bracket_order_stplmt_quantity:", strike_put_bracket_order_stplmt_quantity, "strike_put_bracket_order_profit_quantity:", strike_put_bracket_order_profit_quantity)
                    self.log_file_handle.write("position:" + str(position) + "strike_put_bracket_order_stplmt_quantity:" + str(strike_put_bracket_order_stplmt_quantity) + "strike_put_bracket_order_profit_quantity:" + str(strike_put_bracket_order_profit_quantity) + "\n")
                    print("Unequal bracket profit and stplmt legs: cancelling put profit and loss orders for strike:", strike)
                    self.log_file_handle.write("Unequal bracket profit and stplmt legs: cancelling put profit and loss orders for strike:" + str(strike) + "\n")
                    time.sleep(self.intra_order_sleep_time_ms/1000)
                    self.put_bracket_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
                    self.put_bracket_profit_order_maintenance_on_hold_for_strike[strike] = True #wait until the flag is reset
        #sleep for 1 second
        time.sleep(1)
       

    def updateESPrice(self, newESPrice, testapp : TestApp):
        
        #request market data for surrounding ES FOP contracts
        for strike_off in range(-30, 30, 5):
            is_call_subscription_needed = True
            is_put_subscription_needed = True
            strike = floor(newESPrice) - floor(newESPrice) % 5 + strike_off
            if strike in self.ES_FOP_quote_bid_call:
                is_call_subscription_needed = False
            if strike in self.ES_FOP_quote_ask_call:
                is_call_subscription_needed = False
            if strike in self.ES_FOP_quote_bid_put:
                is_put_subscription_needed = False
            if strike in self.ES_FOP_quote_ask_put:
                is_put_subscription_needed = False
            if is_call_subscription_needed:
                call_contract = Contract()
                call_contract.symbol = "ES"
                call_contract.secType = "FOP"
                call_contract.exchange = "CME"
                call_contract.currency = "USD"
                call_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                call_contract.right = "C"
                call_contract.multiplier = self.es_contract_multiplier
                call_contract.strike = strike
                reqId = testapp.nextOrderId()
                testapp.reqMktData(reqId, call_contract, "", False, False, [])
                testapp.MktDataRequest[reqId] = call_contract
                print("requesting market data for call_contract:", call_contract)
                self.log_file_handle.write("requesting market data for call_contract:" + str(call_contract) + "\n")
            if is_put_subscription_needed:
                put_contract = Contract()
                put_contract.symbol = "ES"
                put_contract.secType = "FOP"
                put_contract.exchange = "CME"
                put_contract.currency = "USD"
                put_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                put_contract.right = "P"
                put_contract.multiplier = self.es_contract_multiplier
                put_contract.strike = strike
                reqId = testapp.nextOrderId()
                testapp.reqMktData(reqId, put_contract, "", False, False, [])
                testapp.MktDataRequest[reqId] = put_contract
                print("requesting market data for put_contract:", put_contract)
                self.log_file_handle.write("requesting market data for put_contract:" + str(put_contract) + "\n")
        #process messages from the IB queue
        self.process_messages_from_ib_queue(testapp)

        #("updateESPrice called with newESPrice:", newESPrice)
        if self.lastESPrice is None and self.currentESPrice is None:
            #wait until price floor modulo 5 is 0
            if floor(newESPrice) % 5 != 0:
                current_time = datetime.datetime.now()
                self.log_file_handle.write(f"waiting for floor(newESPrice) % 5 == 0: time {str(current_time)} price {newESPrice}\n")
                self.sanity_check_and_maintenanace(testapp, newESPrice)
                return
            print("setting lastESPrice and currentESPrice to floor(newESPrice):", floor(newESPrice))
            self.log_file_handle.write("setting lastESPrice and currentESPrice to floor(newESPrice):" + str(floor(newESPrice)) + "\n")
            self.currentESPrice = floor(newESPrice)
            #check whether current strike already has a short straddle position, if so do nothing as we are just restarting at a state of priceDirection = 0
            #if there is no short straddle position, then create a short straddle position with a pseudo priceDirection = 1
            if self.currentESPrice in self.short_call_option_positions and self.currentESPrice in self.short_put_option_positions:
                self.priceDirection = 0
                print("ES bid:", self.currentESPrice, "Initial direction: no change")
                self.log_file_handle.write("ES bid:" + str(self.currentESPrice) + "Initial direction: no change\n")
            else:
                self.lastESPrice = floor(newESPrice) - 5 #FIXME: this is a temporary hack
                self.priceDirection = 1
                print("ES bid:", self.currentESPrice, "Initial direction: up")
                self.log_file_handle.write("ES bid:" + str(self.currentESPrice) + "Initial direction: up\n")

        if self.lastESPrice is not None and self.currentESPrice is not None: 
            self.currentESPrice = newESPrice
        if self.lastESPrice is not None and self.currentESPrice is not None:
            assert self.lastESPrice % 5 == 0
            if self.currentESPrice >= self.lastESPrice + 5:
                self.priceDirection = 1
                print("ES bid:", self.currentESPrice, "direction: up")
                self.log_file_handle.write("ES bid:" + str(self.currentESPrice) + "direction: up\n")
                lastESPrice_ = floor(self.currentESPrice) - floor(self.currentESPrice) % 5

                #first, close all short call positions with strike price less than lastESPrice_
                for strike, position in self.short_call_option_positions.items():
                    if strike < lastESPrice_:
                        if position < 0:
                            short_call_option_contract_to_close = Contract()
                            short_call_option_contract_to_close.symbol = "ES"
                            short_call_option_contract_to_close.secType = "FOP"
                            short_call_option_contract_to_close.exchange = "CME"
                            short_call_option_contract_to_close.currency = "USD"
                            short_call_option_contract_to_close.lastTradeDateOrContractMonth = self.OptionTradeDate
                            short_call_option_contract_to_close.strike = strike
                            short_call_option_contract_to_close.right = "C"
                            short_call_option_contract_to_close.multiplier = self.es_contract_multiplier
                            print("closing short call position for strike:", strike, "short_call_option_contract_to_close:", short_call_option_contract_to_close)
                            self.log_file_handle.write("closing short call position for strike:" + str(strike) + "short_call_option_contract_to_close:" + str(short_call_option_contract_to_close) + "\n")
                            #create closing order by creating a chain of OCO order with conservative to aggressive limit prices with same OCO group id,
                            #then place the orders in OCO group one by one starting with the most conservative order with a time delay between issuing each order
                            #until the order is filled
                            short_call_option_OCA_order_to_close_tuples = []
                            short_call_option_OCAOrderIds = []
                            tick_size = 0.05
                            #decide tick size based on quote price
                            if strike in self.ES_FOP_quote_bid_call:
                                bid_price = self.ES_FOP_quote_bid_call[strike]
                                ask_price = self.ES_FOP_quote_ask_call[strike]
                                spread = ask_price - bid_price
                                if spread >= 0:
                                    if bid_price is not None and ask_price is not None and ask_price >= 10:
                                        tick_size = 0.25
                                    spread_size = int((ask_price - bid_price)/tick_size)
                                    for limit_price_tick_num in range(spread_size+1+2*self.limit_price_slack_ticks):
                                        limit_price = bid_price - self.limit_price_slack_ticks * tick_size + limit_price_tick_num * tick_size
                                        short_call_option_to_close = OrderSamples.LimitOrder("BUY", -position, limit_price)
                                        short_call_option_to_close.orderType = "LMT"
                                        short_call_option_to_close.action = "BUY"
                                        short_call_option_to_close.totalQuantity = -position
                                        short_call_option_to_close.lmtPrice = limit_price
                                        short_call_option_to_close.transmit = self.transmit_orders
                                        short_call_option_to_close.outsideRth = True
                                        short_call_option_OCA_order_to_close_tuple = (limit_price, short_call_option_to_close)
                                        short_call_option_OCA_order_to_close_tuples.append(short_call_option_OCA_order_to_close_tuple)
                                    short_call_option_OCA_orders_to_close = [o for _price, o in short_call_option_OCA_order_to_close_tuples]
                                    OrderSamples.OneCancelsAll("UpCloseShortCallOCO_"+str(testapp.nextValidOrderId), short_call_option_OCA_orders_to_close, 2)
                                    for _price, o in short_call_option_OCA_order_to_close_tuples:
                                        o.account = self.place_orders_to_account
                                        testapp.placeOrder(testapp.nextValidOrderId, short_call_option_contract_to_close, o)
                                        short_call_option_OCAOrderIds.append(testapp.nextValidOrderId)
                                        testapp.nextValidOrderId += 1
                                        self.log_file_handle.write("closing short call position for strike:" + str(strike) + "short_call_option_contract_to_close:" + str(short_call_option_contract_to_close) + "limit_price:" + str(_price) + "\n")
                                        #caccel pending stop limit orders
                                        self.cancelpendingstplmtorder(testapp, strike, "C")
                                        time.sleep(self.intra_order_sleep_time_ms/1000)
                                else:
                                    print("skip closing short call position for strike:", strike, "bid_price:", bid_price, "ask_price:", ask_price, "spread:", spread)
                                    self.log_file_handle.write("skip closing short call position for strike:" + str(strike) + "bid_price:" + str(bid_price) + "ask_price:" + str(ask_price) + "spread:" + str(spread) + "\n")

                #close all short put positions with strike price greater than lastESPrice_
                for strike, position in self.short_put_option_positions.items():
                    if strike > lastESPrice_:
                        if position < 0:
                            short_put_option_contract_to_close = Contract()
                            short_put_option_contract_to_close.symbol = "ES"
                            short_put_option_contract_to_close.secType = "FOP"
                            short_put_option_contract_to_close.exchange = "CME"
                            short_put_option_contract_to_close.currency = "USD"
                            short_put_option_contract_to_close.lastTradeDateOrContractMonth = self.OptionTradeDate
                            short_put_option_contract_to_close.strike = strike
                            short_put_option_contract_to_close.right = "P"
                            short_put_option_contract_to_close.multiplier = self.es_contract_multiplier
                            print("closing short put position for strike:", strike, "short_put_option_contract_to_close:", short_put_option_contract_to_close)
                            self.log_file_handle.write("closing short put position for strike:" + str(strike) + "short_put_option_contract_to_close:" + str(short_put_option_contract_to_close) + "\n")
                            #create closing order by creating a chain of OCO order with conservative to aggressive limit prices with same OCO group id,
                            #then place the orders in OCO group one by one starting with the most conservative order with a time delay between issuing each order
                            #until the order is filled
                            short_put_option_OCA_order_to_close_tuples = []
                            short_put_option_OCAOrderIds = []
                            tick_size = 0.05
                            #decide tick size based on quote price
                            if strike in self.ES_FOP_quote_bid_put:
                                bid_price = self.ES_FOP_quote_bid_put[strike]
                                ask_price = self.ES_FOP_quote_ask_put[strike]
                                spread = ask_price - bid_price
                                if spread >= 0:
                                    if bid_price is not None and ask_price is not None and ask_price >= 10:
                                        tick_size = 0.25
                                    spread_size = int((ask_price - bid_price)/tick_size)
                                    for limit_price_tick_num in range(spread_size+1+2*self.limit_price_slack_ticks):
                                        limit_price = bid_price -self.limit_price_slack_ticks * tick_size + limit_price_tick_num * tick_size
                                        short_put_option_to_close = OrderSamples.LimitOrder("BUY", -position, limit_price)
                                        short_put_option_to_close.orderType = "LMT"
                                        short_put_option_to_close.action = "BUY"
                                        short_put_option_to_close.totalQuantity = -position
                                        short_put_option_to_close.lmtPrice = limit_price
                                        short_put_option_to_close.transmit = self.transmit_orders
                                        short_put_option_to_close.outsideRth = True
                                        short_put_option_OCA_order_to_close_tuple = (limit_price, short_put_option_to_close)
                                        short_put_option_OCA_order_to_close_tuples.append(short_put_option_OCA_order_to_close_tuple)
                                    short_put_option_OCA_orders_to_close = [o for _price, o in short_put_option_OCA_order_to_close_tuples]
                                    OrderSamples.OneCancelsAll("UpCloseShortPutOCO_"+str(testapp.nextValidOrderId), short_put_option_OCA_orders_to_close, 2)
                                    for _price, o in short_put_option_OCA_order_to_close_tuples:
                                        o.account = self.place_orders_to_account
                                        testapp.placeOrder(testapp.nextValidOrderId, short_put_option_contract_to_close, o)
                                        short_put_option_OCAOrderIds.append(testapp.nextValidOrderId)
                                        testapp.nextValidOrderId += 1
                                        self.log_file_handle.write("closing short put position for strike:" + str(strike) + "short_put_option_contract_to_close:" + str(short_put_option_contract_to_close) + "limit_price:" + str(_price) + "\n")
                                        #caccel pending stop limit orders
                                        self.cancelpendingstplmtorder(testapp, strike, "P")
                                        time.sleep(self.intra_order_sleep_time_ms/1000)
                                else:
                                    print("skip closing short put position for strike:", strike, "bid_price:", bid_price, "ask_price:", ask_price, "spread:", spread)
                                    self.log_file_handle.write("skip closing short put position for strike:" + str(strike) + "bid_price:" + str(bid_price) + "ask_price:" + str(ask_price) + "spread:" + str(spread) + "\n")
                                
                up_call_buy_order_needed  = True
                total_long_call_positions = 0
                total_short_call_positions = 0
                for strike, position in self.long_call_option_positions.items():
                    total_long_call_positions += position
                for strike, position in self.short_call_option_positions.items():
                    total_short_call_positions += -position
                if (total_long_call_positions == 0 and total_short_call_positions == 0) or (total_long_call_positions - total_short_call_positions > 5):
                    up_call_buy_order_needed = False
                
                print("total_long_call_positions:", total_long_call_positions, "total_short_call_positions:", total_short_call_positions, "up_call_buy_order_needed:", up_call_buy_order_needed)
                self.log_file_handle.write("total_long_call_positions:" + str(total_long_call_positions) + "total_short_call_positions:" + str(total_short_call_positions) + "up_call_buy_order_needed:" + str(up_call_buy_order_needed) + "\n")

                if up_call_buy_order_needed:
                    #keep issuing up call buy OCO orders to buy a call for 0.50 limit price starting at strike price of currentESPrice + 20 and incrementing by 5 until the OCO order executes.
                    up_call_buy_OCA_order_tuples = []
                    for offset in range(20, self.hedge_outer_offset, 5):
                        up_call_buy_order = OrderSamples.LimitOrder("BUY", 1, 0.50)
                        up_call_buy_order.orderType = "LMT"
                        up_call_buy_order.action = "BUY"
                        up_call_buy_order.totalQuantity = 1
                        up_call_buy_order.lmtPrice = 0.50
                        up_call_buy_order.transmit = self.transmit_orders
                        up_call_buy_order_tuple = (lastESPrice_ + offset, up_call_buy_order)
                        up_call_buy_OCA_order_tuples.append(up_call_buy_order_tuple)
                    up_call_buy_OCA_orders = [o for _strike, o in up_call_buy_OCA_order_tuples]
                    OrderSamples.OneCancelsAll("UpCallBuyWingOCO_"+str(testapp.nextValidOrderId), up_call_buy_OCA_orders, 2)
                    for _strike, o in up_call_buy_OCA_order_tuples:
                        up_call_buy_option_contract = Contract()
                        up_call_buy_option_contract.symbol = "ES"
                        up_call_buy_option_contract.secType = "FOP"
                        up_call_buy_option_contract.exchange = "CME"
                        up_call_buy_option_contract.currency = "USD"
                        up_call_buy_option_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                        up_call_buy_option_contract.strike = _strike
                        up_call_buy_option_contract.right = "C"
                        up_call_buy_option_contract.multiplier = self.es_contract_multiplier
                        
                        print("placing call buy order for strike:", _strike, "up_call_buy_option_contract:", up_call_buy_option_contract)
                        self.log_file_handle.write("placing call buy order for strike:" + str(_strike) + "up_call_buy_option_contract:" + str(up_call_buy_option_contract) + "\n")
                        o.account = self.place_orders_to_account
                        o.outsideRth = True
                        testapp.placeOrder(testapp.nextValidOrderId, up_call_buy_option_contract, o)
                        up_call_buy_OCAOrderId = testapp.nextValidOrderId
                        testapp.nextValidOrderId += 1
                        
                
                up_put_buy_order_needed  = True
                total_long_put_positions = 0
                total_short_put_positions = 0
                for strike, position in self.long_put_option_positions.items():
                    total_long_put_positions += position
                for strike, position in self.short_put_option_positions.items():
                    total_short_put_positions += -position
                if (total_long_put_positions == 0 and total_short_put_positions == 0) or (total_long_put_positions - total_short_put_positions > 5):
                    up_put_buy_order_needed = False
                print("total_long_put_positions:", total_long_put_positions, "total_short_put_positions:", total_short_put_positions, "up_put_buy_order_needed:", up_put_buy_order_needed)
                self.log_file_handle.write("total_long_put_positions:" + str(total_long_put_positions) + "total_short_put_positions:" + str(total_short_put_positions) + "up_put_buy_order_needed:" + str(up_put_buy_order_needed) + "\n")
                
                if up_put_buy_order_needed:
                    #keep issuing up call buy OCO orders to buy a put for 0.50 limit price starting at strike price of currentESPrice - 20 and decrementing by 5 until the OCO order executess.
                    up_put_buy_OCA_order_tuples = []
                    for offset in range(20, self.hedge_outer_offset, 5):
                        up_put_buy_order = OrderSamples.LimitOrder("BUY", 1, 0.50)
                        up_put_buy_order.orderType = "LMT"
                        up_put_buy_order.action = "BUY"
                        up_put_buy_order.totalQuantity = 1
                        up_put_buy_order.lmtPrice = 0.50
                        up_put_buy_order.transmit = self.transmit_orders
                        up_put_buy_order_tuple = (lastESPrice_ - offset, up_put_buy_order)
                        up_put_buy_OCA_order_tuples.append(up_put_buy_order_tuple)
                    up_put_buy_OCA_orders = [o for _strike, o in up_put_buy_OCA_order_tuples]
                    OrderSamples.OneCancelsAll("UpPutBuyWingOCO_"+str(testapp.nextValidOrderId), up_put_buy_OCA_orders, 2)
                    for _strike, o in up_put_buy_OCA_order_tuples:
                        up_put_buy_option_contract = Contract()
                        up_put_buy_option_contract.symbol = "ES"
                        up_put_buy_option_contract.secType = "FOP"
                        up_put_buy_option_contract.exchange = "CME"
                        up_put_buy_option_contract.currency = "USD"
                        up_put_buy_option_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                        up_put_buy_option_contract.strike = _strike
                        up_put_buy_option_contract.right = "P"
                        up_put_buy_option_contract.multiplier = self.es_contract_multiplier
                        
                        print("placing put buy order for strike:", _strike, "up_put_buy_option_contract:", up_put_buy_option_contract)
                        self.log_file_handle.write("placing put buy order for strike:" + str(_strike) + "up_put_buy_option_contract:" + str(up_put_buy_option_contract) + "\n")
                        o.account = self.place_orders_to_account
                        o.outsideRth = True
                        testapp.placeOrder(testapp.nextValidOrderId, up_put_buy_option_contract, o)
                        up_put_buy_OCAOrderId = testapp.nextValidOrderId
                        testapp.nextValidOrderId += 1

                #now that the hedges are ensured, place a straddle order by individually placing a call and put order OCO groups with the same strike price as current strike price
                if self.short_call_option_positions.get(lastESPrice_, 0) == 0:
                    straddle_strike = lastESPrice_
                    short_call_option_contract_to_open = Contract()
                    short_call_option_contract_to_open.symbol = "ES"
                    short_call_option_contract_to_open.secType = "FOP"
                    short_call_option_contract_to_open.exchange = "CME"
                    short_call_option_contract_to_open.currency = "USD"
                    short_call_option_contract_to_open.lastTradeDateOrContractMonth = self.OptionTradeDate
                    short_call_option_contract_to_open.strike = straddle_strike
                    short_call_option_contract_to_open.right = "C"
                    short_call_option_contract_to_open.multiplier = self.es_contract_multiplier
                    print("placing call order for strike:", straddle_strike, "short_call_option_contract_to_open:", short_call_option_contract_to_open)
                    self.log_file_handle.write("placing call order for strike:" + str(straddle_strike) + "short_call_option_contract_to_open:" + str(short_call_option_contract_to_open) + "\n")

                    self.place_short_call_option_to_open_orders(testapp, straddle_strike, short_call_option_contract_to_open)

                if self.short_put_option_positions.get(lastESPrice_, 0) == 0:
                    straddle_strike = lastESPrice_
                    short_put_option_contract_to_open = Contract()
                    short_put_option_contract_to_open.symbol = "ES"
                    short_put_option_contract_to_open.secType = "FOP"
                    short_put_option_contract_to_open.exchange = "CME"
                    short_put_option_contract_to_open.currency = "USD"
                    short_put_option_contract_to_open.lastTradeDateOrContractMonth = self.OptionTradeDate
                    short_put_option_contract_to_open.strike = straddle_strike
                    short_put_option_contract_to_open.right = "P"
                    short_put_option_contract_to_open.multiplier = self.es_contract_multiplier
                    print("placing put order for strike:", straddle_strike, "short_put_option_contract_to_open:", short_put_option_contract_to_open)
                    self.log_file_handle.write("placing put order for strike:" + str(straddle_strike) + "short_put_option_contract_to_open:" + str(short_put_option_contract_to_open) + "\n")

                    self.place_short_put_option_to_open_orders(testapp, straddle_strike, short_put_option_contract_to_open)
                
                self.lastESPrice = lastESPrice_
                print("set new lastESPrice to:", self.lastESPrice)
                self.log_file_handle.write("set new lastESPrice to:" + str(self.lastESPrice) + "\n")
            elif self.currentESPrice <= self.lastESPrice - 5:
                assert self.lastESPrice % 5 == 0
                print("ES bid:", self.currentESPrice, "direction: down")
                self.log_file_handle.write("ES bid:" + str(self.currentESPrice) + "direction: down\n")
                self.priceDirection = -1
                lastESPrice_ = floor(self.currentESPrice) + 5 - floor(self.currentESPrice) % 5
                
                #first, close all short call positions with strike price less than lastESPrice_
                for strike, position in self.short_call_option_positions.items():
                    if strike < lastESPrice_:
                        if position < 0:
                            short_call_option_contract_to_close = Contract()
                            short_call_option_contract_to_close.symbol = "ES"
                            short_call_option_contract_to_close.secType = "FOP"
                            short_call_option_contract_to_close.exchange = "CME"
                            short_call_option_contract_to_close.currency = "USD"
                            short_call_option_contract_to_close.lastTradeDateOrContractMonth = self.OptionTradeDate
                            short_call_option_contract_to_close.strike = strike
                            short_call_option_contract_to_close.right = "C"
                            short_call_option_contract_to_close.multiplier = self.es_contract_multiplier
                            print("closing short call position for strike:", strike, "short_call_option_contract_to_close:", short_call_option_contract_to_close)
                            self.log_file_handle.write("closing short call position for strike:" + str(strike) + "short_call_option_contract_to_close:" + str(short_call_option_contract_to_close) + "\n")
                            #create closing order by creating a chain of OCO order with conservative to aggressive limit prices with same OCO group id,
                            #then place the orders in OCO group one by one starting with the most conservative order with a time delay between issuing each order
                            #until the order is filled
                            short_call_option_OCA_order_to_close_tuples = []
                            short_call_option_OCAOrderIds = []
                            tick_size = 0.05
                            #decide tick size based on quote price
                            if strike in self.ES_FOP_quote_bid_call:
                                bid_price = self.ES_FOP_quote_bid_call[strike]
                                ask_price = self.ES_FOP_quote_ask_call[strike]
                                spread = ask_price - bid_price
                                if spread >= 0:
                                    if bid_price is not None and ask_price is not None and ask_price >= 10:
                                        tick_size = 0.25
                                    spread_size = int((ask_price - bid_price)/tick_size)
                                    for limit_price_tick_num in range(spread_size+1+2*self.limit_price_slack_ticks):
                                        limit_price = bid_price - self.limit_price_slack_ticks * tick_size + limit_price_tick_num * tick_size
                                        short_call_option_to_close = OrderSamples.LimitOrder("BUY", -position, limit_price)
                                        short_call_option_to_close.orderType = "LMT"
                                        short_call_option_to_close.action = "BUY"
                                        short_call_option_to_close.totalQuantity = -position
                                        short_call_option_to_close.lmtPrice = limit_price
                                        short_call_option_to_close.transmit = self.transmit_orders
                                        short_call_option_OCA_order_to_close_tuple = (limit_price, short_call_option_to_close)
                                        short_call_option_OCA_order_to_close_tuples.append(short_call_option_OCA_order_to_close_tuple)
                                    short_call_option_OCA_orders_to_close = [o for _price, o in short_call_option_OCA_order_to_close_tuples]
                                    OrderSamples.OneCancelsAll("DownCloseShortCallOCO_"+str(testapp.nextValidOrderId), short_call_option_OCA_orders_to_close, 2)
                                    for _price, o in short_call_option_OCA_order_to_close_tuples:
                                        o.account = self.place_orders_to_account
                                        o.outsideRth = True
                                        testapp.placeOrder(testapp.nextValidOrderId, short_call_option_contract_to_close, o)
                                        short_call_option_OCAOrderIds.append(testapp.nextValidOrderId)
                                        testapp.nextValidOrderId += 1
                                        self.log_file_handle.write("closing short call position for strike:" + str(strike) + "short_call_option_contract_to_close:" + str(short_call_option_contract_to_close) + "limit_price:" + str(_price) + "\n")
                                        #caccel pending stop limit orders
                                        self.cancelpendingstplmtorder(testapp, strike, "C")
                                        time.sleep(self.intra_order_sleep_time_ms/1000)
                                else:
                                    print("skip closing short call position for strike:", strike, "bid_price:", bid_price, "ask_price:", ask_price, "spread:", spread)
                                    self.log_file_handle.write("skip closing short call position for strike:" + str(strike) + "bid_price:" + str(bid_price) + "ask_price:" + str(ask_price) + "spread:" + str(spread) + "\n")

                #close all short put positions with strike price greater than lastESPrice_
                for strike, position in self.short_put_option_positions.items():
                    if strike > lastESPrice_:
                        if position < 0:
                            short_put_option_contract_to_close = Contract()
                            short_put_option_contract_to_close.symbol = "ES"
                            short_put_option_contract_to_close.secType = "FOP"
                            short_put_option_contract_to_close.exchange = "CME"
                            short_put_option_contract_to_close.currency = "USD"
                            short_put_option_contract_to_close.lastTradeDateOrContractMonth = self.OptionTradeDate
                            short_put_option_contract_to_close.strike = strike
                            short_put_option_contract_to_close.right = "P"
                            short_put_option_contract_to_close.multiplier = self.es_contract_multiplier
                            print("closing short put position for strike:", strike, "short_put_option_contract_to_close:", short_put_option_contract_to_close)
                            self.log_file_handle.write("closing short put position for strike:" + str(strike) + "short_put_option_contract_to_close:" + str(short_put_option_contract_to_close) + "\n")
                            #create closing order by creating a chain of OCO order with conservative to aggressive limit prices with same OCO group id,
                            #then place the orders in OCO group one by one starting with the most conservative order with a time delay between issuing each order
                            #until the order is filled
                            short_put_option_OCA_order_to_close_tuples = []
                            short_put_option_OCAOrderIds = []
                            tick_size = 0.05
                            #decide tick size based on quote price
                            if strike in self.ES_FOP_quote_bid_put:
                                bid_price = self.ES_FOP_quote_bid_put[strike]
                                ask_price = self.ES_FOP_quote_ask_put[strike]
                                spread = ask_price - bid_price
                                if spread >= 0:
                                    if bid_price is not None and ask_price is not None and ask_price >= 10:
                                        tick_size = 0.25
                                    spread_size = int((ask_price - bid_price)/tick_size)
                                    for limit_price_tick_num in range(spread_size+1+2*self.limit_price_slack_ticks):
                                        limit_price = bid_price -self.limit_price_slack_ticks * tick_size + limit_price_tick_num * tick_size
                                        short_put_option_to_close = OrderSamples.LimitOrder("BUY", -position, limit_price)
                                        short_put_option_to_close.orderType = "LMT"
                                        short_put_option_to_close.action = "BUY"
                                        short_put_option_to_close.totalQuantity = -position
                                        short_put_option_to_close.lmtPrice = limit_price
                                        short_put_option_to_close.transmit = self.transmit_orders
                                        short_put_option_OCA_order_to_close_tuple = (limit_price, short_put_option_to_close)
                                        short_put_option_OCA_order_to_close_tuples.append(short_put_option_OCA_order_to_close_tuple)
                                    short_put_option_OCA_orders_to_close = [o for _price, o in short_put_option_OCA_order_to_close_tuples]
                                    OrderSamples.OneCancelsAll("DownCloseShortPutOCO_"+str(testapp.nextValidOrderId), short_put_option_OCA_orders_to_close, 2)
                                    for _price, o in short_put_option_OCA_order_to_close_tuples:
                                        o.account = self.place_orders_to_account
                                        o.outsideRth = True
                                        testapp.placeOrder(testapp.nextValidOrderId, short_put_option_contract_to_close, o)
                                        short_put_option_OCAOrderIds.append(testapp.nextValidOrderId)
                                        testapp.nextValidOrderId += 1
                                        self.log_file_handle.write("closing short put position for strike:" + str(strike) + "short_put_option_contract_to_close:" + str(short_put_option_contract_to_close) + "limit_price:" + str(_price) + "\n")
                                        #caccel pending stop limit orders
                                        self.cancelpendingstplmtorder(testapp, strike, "P")
                                        time.sleep(self.intra_order_sleep_time_ms/1000)
                                else:
                                    print("skip closing short put position for strike:", strike, "bid_price:", bid_price, "ask_price:", ask_price, "spread:", spread)
                                    self.log_file_handle.write("skip closing short put position for strike:" + str(strike) + "bid_price:" + str(bid_price) + "ask_price:" + str(ask_price) + "spread:" + str(spread) + "\n")
                                
                down_call_buy_order_needed  = True
                total_long_call_positions = 0
                total_short_call_positions = 0
                for strike, position in self.long_call_option_positions.items():
                    total_long_call_positions += position
                for strike, position in self.short_call_option_positions.items():
                    total_short_call_positions += -position
                if (total_long_call_positions == 0 and total_short_call_positions == 0) or (total_long_call_positions - total_short_call_positions > 5):
                    down_call_buy_order_needed = False
                print("total_long_call_positions:", total_long_call_positions, "total_short_call_positions:", total_short_call_positions, "down_call_buy_order_needed:", down_call_buy_order_needed)
                self.log_file_handle.write("total_long_call_positions:" + str(total_long_call_positions) + "total_short_call_positions:" + str(total_short_call_positions) + "down_call_buy_order_needed:" + str(down_call_buy_order_needed) + "\n")

                if down_call_buy_order_needed:
                    #keep issuing down call buy OCO orders to buy a put for 0.50 limit price starting at strike price of currentESPrice + 20 and incrementing by 5 until the OCO order executes.
                    down_call_buy_OCA_order_tuples = []
                    for offset in range(20, self.hedge_outer_offset, 5):
                        down_call_buy_order = OrderSamples.LimitOrder("BUY", 1, 0.50)
                        down_call_buy_order.orderType = "LMT"
                        down_call_buy_order.action = "BUY"
                        down_call_buy_order.totalQuantity = 1
                        down_call_buy_order.lmtPrice = 0.50
                        down_call_buy_order.transmit = self.transmit_orders
                        down_call_buy_order_tuple = (lastESPrice_ + offset, down_call_buy_order)
                        down_call_buy_OCA_order_tuples.append(down_call_buy_order_tuple)
                    down_call_buy_OCA_orders = [o for _strike, o in down_call_buy_OCA_order_tuples]
                    OrderSamples.OneCancelsAll("DownCallBuyWingOCO_"+str(testapp.nextValidOrderId), down_call_buy_OCA_orders, 2)
                    for _strike, o in down_call_buy_OCA_order_tuples:
                        down_call_buy_option_contract = Contract()
                        down_call_buy_option_contract.symbol = "ES"
                        down_call_buy_option_contract.secType = "FOP"
                        down_call_buy_option_contract.exchange = "CME"
                        down_call_buy_option_contract.currency = "USD"
                        down_call_buy_option_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                        down_call_buy_option_contract.strike = _strike
                        down_call_buy_option_contract.right = "C"
                        down_call_buy_option_contract.multiplier = self.es_contract_multiplier
                        
                        print("placing call buy order for strike:", _strike, "down_call_buy_option_contract:", down_call_buy_option_contract)
                        self.log_file_handle.write("placing call buy order for strike:" + str(_strike) + "down_call_buy_option_contract:" + str(down_call_buy_option_contract) + "\n")
                        o.account = self.place_orders_to_account
                        o.outsideRth = True
                        testapp.placeOrder(testapp.nextValidOrderId, down_call_buy_option_contract, o)
                        down_call_buy_OCAOrderId = testapp.nextValidOrderId
                        testapp.nextValidOrderId += 1
                        self.log_file_handle.write("placing call buy order for strike:" + str(_strike) + "down_call_buy_option_contract:" + str(down_call_buy_option_contract) + "\n")

                    

                down_put_buy_order_needed  = True
                total_long_put_positions = 0
                total_short_put_positions = 0
                for strike, position in self.long_put_option_positions.items():
                    total_long_put_positions += position
                for strike, position in self.short_put_option_positions.items():
                    total_short_put_positions += -position
                if (total_long_put_positions == 0 and total_short_put_positions == 0) or (total_long_put_positions - total_short_put_positions > 5):
                    down_put_buy_order_needed = False
                print("total_long_put_positions:", total_long_put_positions, "total_short_put_positions:", total_short_put_positions, "down_put_buy_order_needed:", down_put_buy_order_needed)
                self.log_file_handle.write("total_long_put_positions:" + str(total_long_put_positions) + "total_short_put_positions:" + str(total_short_put_positions) + "down_put_buy_order_needed:" + str(down_put_buy_order_needed) + "\n")
                
                if down_put_buy_order_needed:
                    #keep issuing down put buy OCO orders to buy a put for 0.50 limit price starting at strike price of currentESPrice - 20 and decrementing by 5 until the OCO order executes.
                    down_put_buy_OCA_order_tuples = []
                    for offset in range(20, self.hedge_outer_offset, 5):
                        down_put_buy_order = OrderSamples.LimitOrder("BUY", 1, 0.50)
                        down_put_buy_order.orderType = "LMT"
                        down_put_buy_order.action = "BUY"
                        down_put_buy_order.totalQuantity = 1
                        down_put_buy_order.lmtPrice = 0.50
                        down_put_buy_order.transmit = self.transmit_orders
                        down_put_buy_order_tuple = (lastESPrice_ - offset, down_put_buy_order)
                        down_put_buy_OCA_order_tuples.append(down_put_buy_order_tuple)
                    down_put_buy_OCA_orders = [o for _strike, o in down_put_buy_OCA_order_tuples]
                    OrderSamples.OneCancelsAll("DownPutBuyWingOCO_"+str(testapp.nextValidOrderId), down_put_buy_OCA_orders, 2)
                    for _strike, o in down_put_buy_OCA_order_tuples:
                        down_put_buy_option_contract = Contract()
                        down_put_buy_option_contract.symbol = "ES"
                        down_put_buy_option_contract.secType = "FOP"
                        down_put_buy_option_contract.exchange = "CME"
                        down_put_buy_option_contract.currency = "USD"
                        down_put_buy_option_contract.lastTradeDateOrContractMonth = self.OptionTradeDate
                        down_put_buy_option_contract.strike = _strike
                        down_put_buy_option_contract.right = "P"
                        down_put_buy_option_contract.multiplier =  self.es_contract_multiplier
                        
                        print("placing put buy order for strike:", _strike, "down_put_buy_option_contract:", down_put_buy_option_contract)
                        self.log_file_handle.write("placing put buy order for strike:" + str(_strike) + "down_put_buy_option_contract:" + str(down_put_buy_option_contract) + "\n")
                        o.account = self.place_orders_to_account
                        o.outsideRth = True
                        testapp.placeOrder(testapp.nextValidOrderId, down_put_buy_option_contract, o)
                        down_put_buy_OCAOrderId = testapp.nextValidOrderId
                        testapp.nextValidOrderId += 1
                        self.log_file_handle.write("placing put buy order for strike:" + str(_strike) + "down_put_buy_option_contract:" + str(down_put_buy_option_contract) + "\n")
                    
                #now that the hedges are ensured, place a straddle order by individually placing a call and put order OCO groups with the same strike price as current strike price
                if self.short_call_option_positions.get(lastESPrice_, 0) == 0:
                    straddle_strike = lastESPrice_
                    short_call_option_contract_to_open = Contract()
                    short_call_option_contract_to_open.symbol = "ES"
                    short_call_option_contract_to_open.secType = "FOP"
                    short_call_option_contract_to_open.exchange = "CME"
                    short_call_option_contract_to_open.currency = "USD"
                    short_call_option_contract_to_open.lastTradeDateOrContractMonth = self.OptionTradeDate
                    short_call_option_contract_to_open.strike = straddle_strike
                    short_call_option_contract_to_open.right = "C"
                    short_call_option_contract_to_open.multiplier = self.es_contract_multiplier
                    print("placing call order for strike:", straddle_strike, "short_call_option_contract_to_open:", short_call_option_contract_to_open)
                    self.log_file_handle.write("placing call order for strike:" + str(straddle_strike) + "short_call_option_contract_to_open:" + str(short_call_option_contract_to_open) + "\n")                    
                    self.place_short_call_option_to_open_orders(testapp, straddle_strike, short_call_option_contract_to_open)
                    
                if self.short_put_option_positions.get(lastESPrice_, 0) == 0:
                    straddle_strike = lastESPrice_
                    short_put_option_contract_to_open = Contract()
                    short_put_option_contract_to_open.symbol = "ES"
                    short_put_option_contract_to_open.secType = "FOP"
                    short_put_option_contract_to_open.exchange = "CME"
                    short_put_option_contract_to_open.currency = "USD"
                    short_put_option_contract_to_open.lastTradeDateOrContractMonth = self.OptionTradeDate
                    short_put_option_contract_to_open.strike = straddle_strike
                    short_put_option_contract_to_open.right = "P"
                    short_put_option_contract_to_open.multiplier = self.es_contract_multiplier
                    print("placing put order for strike:", straddle_strike, "short_put_option_contract_to_open:", short_put_option_contract_to_open)
                    self.log_file_handle.write("placing put order for strike:" + str(straddle_strike) + "short_put_option_contract_to_open:" + str(short_put_option_contract_to_open) + "\n")
                    self.place_short_put_option_to_open_orders(testapp, straddle_strike, short_put_option_contract_to_open)

                self.lastESPrice = lastESPrice_
                print("set new lastESPrice to:", self.lastESPrice)
                self.log_file_handle.write("set new lastESPrice to:" + str(self.lastESPrice) + "\n")
            else:
                assert self.lastESPrice % 5 == 0
                self.priceDirection = 0
                current_time = datetime.datetime.now()
                self.log_file_handle.write("ES price update: " + str(self.currentESPrice) + " direction: no change " + " current_time: " + str(current_time) + "\n")
        self.sanity_check_and_maintenanace(testapp, newESPrice)

    def place_short_put_option_to_open_orders(self, testapp, straddle_strike, short_put_option_contract_to_open):
        short_put_option_OCA_order_to_open_tuples = []
        short_put_option_OCAOrderIds = []
        short_put_option_bracket_order_tuples = []
        tick_size = 0.05
        #decide tick size based on quote price
        if straddle_strike in self.ES_FOP_quote_bid_put:
            bid_price = self.ES_FOP_quote_bid_put[straddle_strike]
            ask_price = self.ES_FOP_quote_ask_put[straddle_strike]
            spread = ask_price - bid_price
            if spread >= 0:
                if bid_price is not None and ask_price is not None and ask_price >= 10:
                    tick_size = 0.25
                spread_size = int((ask_price - bid_price)/tick_size)
                for limit_price_tick_num in reversed(range(spread_size+1+2*self.limit_price_slack_ticks)):
                    limit_price = bid_price - self.limit_price_slack_ticks * tick_size + limit_price_tick_num * tick_size
                    short_put_option_to_open = OrderSamples.LimitOrder("SELL", 1, limit_price)
                    short_put_option_to_open.orderType = "LMT"
                    short_put_option_to_open.action = "SELL"
                    short_put_option_to_open.totalQuantity = 1
                    short_put_option_to_open.lmtPrice = limit_price
                    short_put_option_to_open.transmit = self.transmit_orders if not self.attach_bracket_order else False
                    short_put_option_OCA_order_to_open_tuple = (limit_price, short_put_option_to_open)
                    short_put_option_OCA_order_to_open_tuples.append(short_put_option_OCA_order_to_open_tuple)
                    if self.attach_bracket_order:
                        short_put_option_to_open_profit_order_limit_price = limit_price/self.profit_target_divisor
                        if short_put_option_to_open_profit_order_limit_price >= 10:
                            short_put_option_to_open_profit_order_limit_price = round(short_put_option_to_open_profit_order_limit_price * 4) / 4
                        else:
                            short_put_option_to_open_profit_order_limit_price = round(short_put_option_to_open_profit_order_limit_price * 20) / 20
                        short_put_option_to_open_profit_order_stop_price = limit_price + self.stop_loss_increment
                        if short_put_option_to_open_profit_order_stop_price >= 10:
                            short_put_option_to_open_profit_order_stop_price = round(short_put_option_to_open_profit_order_stop_price * 4) / 4
                        else:
                            short_put_option_to_open_profit_order_stop_price = round(short_put_option_to_open_profit_order_stop_price * 20) / 20
                        short_put_option_to_open_profit_order_stop_limit_price = short_put_option_to_open_profit_order_stop_price + self.stop_limit_increment
                        if short_put_option_to_open_profit_order_stop_limit_price >= 10:
                            short_put_option_to_open_profit_order_stop_limit_price = round(short_put_option_to_open_profit_order_stop_limit_price * 4) / 4
                        else:
                            short_put_option_to_open_profit_order_stop_limit_price = round(short_put_option_to_open_profit_order_stop_limit_price * 20) / 20
                        short_put_option_to_open_profit_order = OrderSamples.LimitOrder("BUY", 1, short_put_option_to_open_profit_order_limit_price)
                        short_put_option_to_open_profit_order.orderType = "LMT"
                        short_put_option_to_open_profit_order.action = "BUY"
                        short_put_option_to_open_profit_order.totalQuantity = 1
                        short_put_option_to_open_profit_order.lmtPrice = short_put_option_to_open_profit_order_limit_price
                        short_put_option_to_open_profit_order.transmit = False
                        short_put_option_to_open_loss_order = Order()
                        short_put_option_to_open_loss_order.orderType = "STP LMT"
                        short_put_option_to_open_loss_order.action = "BUY"
                        short_put_option_to_open_loss_order.totalQuantity = 1
                        short_put_option_to_open_loss_order.auxPrice = short_put_option_to_open_profit_order_stop_price
                        short_put_option_to_open_loss_order.lmtPrice = short_put_option_to_open_profit_order_stop_limit_price
                        short_put_option_to_open_loss_order.transmit = self.transmit_orders
                        short_put_option_bracket_order_tuple = (short_put_option_to_open_profit_order, short_put_option_to_open_loss_order)
                        short_put_option_bracket_order_tuples.append(short_put_option_bracket_order_tuple)
                short_put_option_OCA_orders_to_open = [o for _price, o in short_put_option_OCA_order_to_open_tuples]
                OrderSamples.OneCancelsAll("UpShortPutOCO_"+str(testapp.nextValidOrderId), short_put_option_OCA_orders_to_open, 2)
                for _price, o in short_put_option_OCA_order_to_open_tuples:
                    o.account = self.place_orders_to_account
                    o.outsideRth = True
                    short_put_option_to_open_order_id = testapp.nextValidOrderId
                    testapp.placeOrder(short_put_option_to_open_order_id, short_put_option_contract_to_open, o)
                    short_put_option_OCAOrderIds.append(short_put_option_to_open_order_id)
                    testapp.nextValidOrderId += 1
                    if self.attach_bracket_order:
                        short_put_option_to_open_profit_order, short_put_option_to_open_loss_order = short_put_option_bracket_order_tuples.pop()
                        short_put_option_to_open_profit_order.account = self.place_orders_to_account
                        short_put_option_to_open_profit_order.parentId = short_put_option_to_open_order_id
                        short_put_option_to_open_profit_order.outsideRth = True
                        short_put_option_to_open_profit_order.triggerMethod = 1
                        short_put_option_to_open_loss_order.account = self.place_orders_to_account
                        short_put_option_to_open_loss_order.parentId = short_put_option_to_open_order_id
                        short_put_option_to_open_loss_order.outsideRth = True
                        short_put_option_to_open_loss_order.triggerMethod = 1
                        testapp.placeOrder(testapp.nextValidOrderId, short_put_option_contract_to_open, short_put_option_to_open_profit_order)
                        testapp.nextValidOrderId += 1
                        testapp.placeOrder(testapp.nextValidOrderId, short_put_option_contract_to_open, short_put_option_to_open_loss_order)
                        testapp.nextValidOrderId += 1
                    self.log_file_handle.write("placing put order for strike:" + str(straddle_strike) + "limit_price:" + str(_price) + "short_put_option_contract_to_open:" + str(short_put_option_contract_to_open) + "profit_order:" + str(short_put_option_to_open_profit_order) + "loss_order:" + str(short_put_option_to_open_loss_order) + "\n")
                    time.sleep(self.intra_order_sleep_time_ms/1000)
            else:
                print("skip placing put order for strike:", straddle_strike, "bid_price:", bid_price, "ask_price:", ask_price, "spread:", spread)
                self.log_file_handle.write("skip placing put order for strike:" + str(straddle_strike) + "bid_price:" + str(bid_price) + "ask_price:" + str(ask_price) + "spread:" + str(spread) + "\n")

    def place_short_call_option_to_open_orders(self, testapp, straddle_strike, short_call_option_contract_to_open):
        short_call_option_OCA_order_to_open_tuples = []
        short_call_option_OCAOrderIds = []
        short_call_option_bracket_order_tuples = []
        tick_size = 0.05
                    #decide tick size based on quote price
        if straddle_strike in self.ES_FOP_quote_bid_call:
            bid_price = self.ES_FOP_quote_bid_call[straddle_strike]
            ask_price = self.ES_FOP_quote_ask_call[straddle_strike]
            spread = ask_price - bid_price
            if spread >= 0:
                if bid_price is not None and ask_price is not None and ask_price >= 10:
                    tick_size = 0.25
                spread_size = int((ask_price - bid_price)/tick_size)
                for limit_price_tick_num in reversed(range(spread_size+1+2*self.limit_price_slack_ticks)):
                    limit_price = bid_price - self.limit_price_slack_ticks * tick_size + limit_price_tick_num * tick_size
                    short_call_option_to_open = OrderSamples.LimitOrder("SELL", 1, limit_price)
                    short_call_option_to_open.orderType = "LMT"
                    short_call_option_to_open.action = "SELL"
                    short_call_option_to_open.totalQuantity = 1
                    short_call_option_to_open.lmtPrice = limit_price
                    short_call_option_to_open.transmit = self.transmit_orders if not self.attach_bracket_order else False
                    short_call_option_OCA_order_to_open_tuple = (limit_price, short_call_option_to_open)
                    short_call_option_OCA_order_to_open_tuples.append(short_call_option_OCA_order_to_open_tuple)
                    if self.attach_bracket_order:
                        short_call_option_to_open_profit_order_limit_price = limit_price/self.profit_target_divisor
                        if short_call_option_to_open_profit_order_limit_price >= 10:
                            short_call_option_to_open_profit_order_limit_price = round(short_call_option_to_open_profit_order_limit_price * 4) / 4
                        else:
                            short_call_option_to_open_profit_order_limit_price = round(short_call_option_to_open_profit_order_limit_price * 20) / 20
                        short_call_option_to_open_profit_order_stop_price = limit_price + self.stop_loss_increment
                        if short_call_option_to_open_profit_order_stop_price >= 10:
                            short_call_option_to_open_profit_order_stop_price = round(short_call_option_to_open_profit_order_stop_price * 4) / 4
                        else:
                            short_call_option_to_open_profit_order_stop_price = round(short_call_option_to_open_profit_order_stop_price * 20) / 20
                        short_call_option_to_open_profit_order_stop_limit_price = short_call_option_to_open_profit_order_stop_price + self.stop_limit_increment
                        if short_call_option_to_open_profit_order_stop_limit_price >= 10:
                            short_call_option_to_open_profit_order_stop_limit_price = round(short_call_option_to_open_profit_order_stop_limit_price * 4) / 4
                        else:
                            short_call_option_to_open_profit_order_stop_limit_price = round(short_call_option_to_open_profit_order_stop_limit_price * 20) / 20
                        short_call_option_to_open_profit_order = OrderSamples.LimitOrder("BUY", 1, short_call_option_to_open_profit_order_limit_price)
                        short_call_option_to_open_profit_order.orderType = "LMT"
                        short_call_option_to_open_profit_order.action = "BUY"
                        short_call_option_to_open_profit_order.totalQuantity = 1
                        short_call_option_to_open_profit_order.lmtPrice = short_call_option_to_open_profit_order_limit_price
                        short_call_option_to_open_profit_order.transmit = False
                        short_call_option_to_open_loss_order = Order()
                        short_call_option_to_open_loss_order.orderType = "STP LMT"
                        short_call_option_to_open_loss_order.action = "BUY"
                        short_call_option_to_open_loss_order.totalQuantity = 1
                        short_call_option_to_open_loss_order.auxPrice = short_call_option_to_open_profit_order_stop_price
                        short_call_option_to_open_loss_order.lmtPrice = short_call_option_to_open_profit_order_stop_limit_price
                        short_call_option_to_open_loss_order.transmit = self.transmit_orders
                        short_call_option_bracket_order_tuple = (short_call_option_to_open_profit_order, short_call_option_to_open_loss_order)
                        short_call_option_bracket_order_tuples.append(short_call_option_bracket_order_tuple)
                short_call_option_OCA_orders_to_open = [o for _price, o in short_call_option_OCA_order_to_open_tuples]
                OrderSamples.OneCancelsAll("UpShortCallOCO_"+str(testapp.nextValidOrderId), short_call_option_OCA_orders_to_open, 2)
                for _price, o in short_call_option_OCA_order_to_open_tuples:
                    o.account = self.place_orders_to_account
                    o.outsideRth = True
                    short_call_option_to_open_order_id = testapp.nextValidOrderId
                    testapp.placeOrder(short_call_option_to_open_order_id, short_call_option_contract_to_open, o)
                    short_call_option_OCAOrderIds.append(short_call_option_to_open_order_id)
                    testapp.nextValidOrderId += 1
                    if self.attach_bracket_order:
                        short_call_option_to_open_profit_order, short_call_option_to_open_loss_order = short_call_option_bracket_order_tuples.pop()
                        short_call_option_to_open_profit_order.account = self.place_orders_to_account
                        short_call_option_to_open_profit_order.parentId = short_call_option_to_open_order_id
                        short_call_option_to_open_profit_order.outsideRth = True
                        short_call_option_to_open_profit_order.triggerMethod = 1
                        short_call_option_to_open_loss_order.account = self.place_orders_to_account
                        short_call_option_to_open_loss_order.parentId = short_call_option_to_open_order_id
                        short_call_option_to_open_loss_order.outsideRth = True
                        short_call_option_to_open_loss_order.triggerMethod = 1
                        testapp.placeOrder(testapp.nextValidOrderId, short_call_option_contract_to_open, short_call_option_to_open_profit_order)
                        testapp.nextValidOrderId += 1
                        testapp.placeOrder(testapp.nextValidOrderId, short_call_option_contract_to_open, short_call_option_to_open_loss_order)
                        testapp.nextValidOrderId += 1
                    self.log_file_handle.write("placing call order for strike:" + str(straddle_strike) + "limit_price:" + str(_price) + "short_call_option_contract_to_open:" + str(short_call_option_contract_to_open) + "profit_order:" + str(short_call_option_to_open_profit_order) + "loss_order:" + str(short_call_option_to_open_loss_order) + "\n")
                    time.sleep(self.intra_order_sleep_time_ms/1000)
            else:
                print("skip placing call order for strike:", straddle_strike, "bid_price:", bid_price, "ask_price:", ask_price, "spread:", spread)
                self.log_file_handle.write("skip placing call order for strike:" + str(straddle_strike) + "bid_price:" + str(bid_price) + "ask_price:" + str(ask_price) + "spread:" + str(spread) + "\n")

def main():
    SetupLogger()
    logging.debug("now is %s", datetime.datetime.now())
    logging.getLogger().setLevel(logging.ERROR)

    cmdLineParser = argparse.ArgumentParser("api tests")
    # cmdLineParser.add_option("-c", action="store_True", dest="use_cache", default = False, help = "use the cache")
    # cmdLineParser.add_option("-f", action="store", type="string", dest="file", default="", help="the input file")
    cmdLineParser.add_argument("-p", "--port", action="store", type=int,
                               dest="port", default=7496, help="The TCP port to use")
    cmdLineParser.add_argument("-C", "--global-cancel", action="store_true",
                               dest="global_cancel", default=False,
                               help="whether to trigger a globalCancel req")
    args = cmdLineParser.parse_args()
    print("Using args", args)
    logging.debug("Using args %s", args)
    # print(args)


    # enable logging when member vars are assigned
    from ibapi import utils
    Order.__setattr__ = utils.setattr_log
    Contract.__setattr__ = utils.setattr_log
    DeltaNeutralContract.__setattr__ = utils.setattr_log
    TagValue.__setattr__ = utils.setattr_log
    TimeCondition.__setattr__ = utils.setattr_log
    ExecutionCondition.__setattr__ = utils.setattr_log
    MarginCondition.__setattr__ = utils.setattr_log
    PriceCondition.__setattr__ = utils.setattr_log
    PercentChangeCondition.__setattr__ = utils.setattr_log
    VolumeCondition.__setattr__ = utils.setattr_log

    # from inspect import signature as sig
    # import code code.interact(local=dict(globals(), **locals()))
    # sys.exit(1)

    # tc = TestClient(None)
    # tc.reqMktData(1101, ContractSamples.USStockAtSmart(), "", False, None)
    # print(tc.reqId2nReq)
    # sys.exit(1)
    alive = True
    while alive:
        try:
            app = TestApp()
            if args.global_cancel:
                app.globalCancelOnly = True
            # ! [connect]
            app.connect("127.0.0.1", args.port, clientId=0)
            # ! [connect]
            print("serverVersion:%s connectionTime:%s" % (app.serverVersion(),
                                                        app.twsConnectionTime()))

            # ! [clientrun]
            app.run()
            # ! [clientrun]
        #handle keyboard interrupt
        except KeyboardInterrupt:
            print("Keyboard interrupt")
            alive = False
        except Exception as e:
            print("Exception:", e)
            if app.nextValidOrderId:
                app.nextValidOrderId += 1
        finally:
            #app.dumpTestCoverageSituation()
            #app.dumpReqAnsErrSituation()
            app.disconnect()


if __name__ == "__main__":
    main()
