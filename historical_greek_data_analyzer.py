#historical greek data analyzer. reads json data files, analyzes them, and displays data on a web dashboard
import json
from math import ceil, floor
import os
import sys
import re
from datetime import datetime
import concurrent.futures
import time

def plot_strikes_time_series(call_strikes_series, put_strikes_series):
                import matplotlib.pyplot as plt

                # Plot call strikes time series
                call_tick_iv = {}
                for call_strike in call_strikes_series:
                    call_tick_iv[call_strike] = call_strikes_series[call_strike][9]
                call_strikes = list(call_tick_iv.keys())
                call_iv_series = list(call_tick_iv.values())

                plt.plot(call_strikes, call_iv_series, label='Call Strikes')

                # Plot put strikes time series
                put_tick_iv = {}
                for put_strike in put_strikes_series:
                    put_tick_iv[put_strike] = put_strikes_series[put_strike][9]
                put_strikes = list(put_tick_iv.keys())
                put_iv_series = list(put_tick_iv.values())

                plt.plot(put_strikes, put_iv_series, label='Put Strikes')

                plt.xlabel('Strike Price')
                plt.ylabel('Tick Value')
                plt.title('Call and Put Strikes Time Series')
                plt.legend()
                plt.show()


class ReadData:
    def __init__(self, expiration_date):
        self.data_type = "bulk_historical_greeks"
        self.ticker = "SPXW"
        self.expiration_date = expiration_date
        self.start_date = expiration_date
        self.end_date = expiration_date
        self.expiration_date = expiration_date
        self.ticker = "SPXW"
        self.data_type = "bulk_historical_greeks"
        self.ivl = 60000
        self.page_num = 0
        self.input_path = "C:\\Thetadata\\" + self.data_type + "\\" + self.ticker + "\\" + self.expiration_date + "\\"
        self.data = []
        self.start_ms = 34260000
        self.end_ms = 57600000
        self.ivl = 60000
        self.time_series = {} #key is start ms for an ivl, value is data array for that ms as tuple (contract, tick)
        self.call_strikes_series = {} #(strike, (tick, ms))
        self.put_strikes_series = {} #(strike, (tick, ms))
        self.chain_strike_series = {}  #(strike, [(call_tick, ms)), ((put_tick, ms)])
        self.simulation_series = []
    def read_data(self):
        page_is_valid = True
        return_success = True
        try:
            while page_is_valid:
                with open(self.input_path + self.ticker + "_" + self.data_type + "_" + self.expiration_date + "_" + self.start_date + "_" + str(self.ivl) + "_" + str(self.page_num) + ".json", "r") as f:
                    self.data.append(json.load(f))
                    self.page_num += 1
                    if not os.path.exists(self.input_path + self.ticker + "_" + self.data_type + "_" + self.expiration_date + "_" + self.start_date + "_" + str(self.ivl) + "_" + str(self.page_num) + ".json"):
                        page_is_valid = False
        except Exception as e:
            print("Error reading data: " + str(e))
            return_success = False
        return return_success

    def make_time_series(self):
        total_pages = len(self.data)
        print("Making time series for " + self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date + ": " + str(total_pages) + " pages of data")
        #get header format information
        header = self.data[0]["header"]["format"]
        for page_num in range(total_pages):
            response_data = self.data[page_num]["response"]
            #response_data is a json array of objects with ticks and contract data per object
            for data in response_data:
                ticks = data["ticks"]
                contract = data["contract"]
                last_ms_key = self.start_ms - self.ivl
                last_contract = None
                last_tick = None
                for tick in ticks:
                    ms_key = tick[0]
                    if ms_key < self.start_ms or ms_key > self.end_ms:
                        continue
                    if ms_key < last_ms_key:
                        print("Out of order tick: " + str(ms_key) + " for contract: " + str(contract))
                        continue
                    if last_contract is not None and last_tick is not None:
                        for i in range(last_ms_key + self.ivl, ms_key, self.ivl):
                            if i not in self.time_series:
                                self.time_series[i] = []
                            self.time_series[i].append((last_contract, last_tick))
                    if ms_key not in self.time_series:
                        self.time_series[ms_key] = []
                    self.time_series[ms_key].append((contract, tick))
                    last_ms_key = ms_key
                    last_contract = contract
                    last_tick = tick
                    #print("Tick: " + str(tick))
                    #time.sleep(1)
                
    
    def simulate_time_series(self):
        print("Simulating time series for " + self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date + " with " + str(len(self.time_series)) + " ms keys")
        for ms_key in self.time_series:
            print("At time: " + str(ms_key))
            contract_tick_values = self.time_series[ms_key]
            for contract, tick in contract_tick_values:
                #print("@time:" + str(ms_key) + " Contract: " + str(contract) + " Tick: " + str(tick))
                strike = contract['strike']
                if contract['right'] == 'C':
                    self.call_strikes_series[strike] = (tick, ms_key)
                    if strike not in self.chain_strike_series:
                        self.chain_strike_series[strike] = [None, None]
                    self.chain_strike_series[strike][0] = (tick, ms_key)
                else:
                    self.put_strikes_series[strike] = (tick, ms_key)
                    if strike not in self.chain_strike_series:
                        self.chain_strike_series[strike] = [None, None]
                    self.chain_strike_series[strike][1] = (tick, ms_key)
            
            
            for strike in self.chain_strike_series:
                #sanity check
                call_tick, ms_key = self.chain_strike_series[strike][0]
                put_tick, ms_key = self.chain_strike_series[strike][1]
                #print("Strike: " + str(strike) + " Call: " + str(call_tick) + " Put: " + str(put_tick))
            
            #atm_strike, atm_diff = find_atm_strike(self.chain_strike_series)
            #print("ATM Strike: " + str(atm_strike) + " ATM Diff: " + str(atm_diff), " Call: " + str(self.chain_strike_series[atm_strike][0]), " Put: " + str(self.chain_strike_series[atm_strike][1])) 
            
            inferred_spot_price, actual_spot_price = infer_spot_price_from_chain(self.chain_strike_series)
            error = actual_spot_price - inferred_spot_price
            print("@ms:" + str(ms_key) + " Inferred Spot Price: " + str(inferred_spot_price) + " Actual Spot Price: " + str(actual_spot_price), " Error: " + str(error))
            _chain_strike_series = {}
            for strike in self.chain_strike_series:
                call_tick, call_ms_key = self.chain_strike_series[strike][0]
                put_tick, put_ms_key = self.chain_strike_series[strike][1]
                _chain_strike_series[strike] = [(call_tick,call_ms_key), (put_tick, put_ms_key)]
            #print("ms from chain:", chain_strike_series[list(chain_strike_series.keys())[0]][0][1])
            self.simulation_series.append((ms_key, _chain_strike_series, inferred_spot_price))
            #print("ms from chain:", chain_strike_series[list(chain_strike_series.keys())[0]][0][1], "last added e.g.:", self.simulation_series[-1][1][list(self.simulation_series[-1][1].keys())[0]])
            #sample_series1 = self.simulation_series[0]
            #print("len:" + str(len(self.simulation_series)) + " ms_key in sample:" + str(sample_series1[0]) + " sample series:", sample_series1[1][list(sample_series1[1].keys())[0]])
            #if len(self.simulation_series) > 1:
            #    sample_series2 = self.simulation_series[1]
            #    print("len:" + str(len(self.simulation_series)) + " ms_key in sample:" + str(sample_series2[0])+ " sample series:", sample_series2[1][list(sample_series2[1].keys())[0]])
        
        print("Time series simulated for " + self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date)

class TradingStrategy:
    def __init__(self, simulation_series, trading_policies):
        self.simulation_series = simulation_series
        self.trading_policies = trading_policies
    def do_simulation(self):  #executes trading policy functions on simulated time series
        for ms_key, sim_chain_strike_series, spot_price in self.simulation_series:
            for trading_policy in self.trading_policies:
                #print("Trading strategy: @ms:" + str(ms_key) + " Spot Price: " + str(spot_price))
                #print("Trading strategy: Chain Strike Series: " + str(chain_strike_series))
                trading_policy.do_trading(sim_chain_strike_series, spot_price)

class TradingPolicy:
    def __init__(self):
        self.last_spot_price = None
        self.last_chain_strike_series = None
        self.last_strike = None
        self.positions = {} #key is strike, value is [] of (count, side, price) tuples
        self.trades = [] #list of (time, strike, side, price, count) tuples
        self.trading_policy_function = None
        
    def do_trading(self, _sim_chain_strike_series, spot_price):
        self.trading_policy_function(self, _sim_chain_strike_series, spot_price)

def trading_policy1_function(trading_policy,__sim_chain_strike_series, spot_price):
    #print("Trading policy 1: Chain Strike Series: " + str(chain_strike_series) + " Spot Price: " + str(spot_price))
    atm_strike_floor = floor(spot_price/5)*5
    atm_strike_ceil = ceil(spot_price/5)*5

    if trading_policy.last_spot_price is None:
        trading_policy.last_spot_price = spot_price
        trading_policy.last_chain_strike_series = __sim_chain_strike_series
        trading_policy.last_strike = atm_strike_floor
        return
    strike_moved_up = False
    strike_moved_down = False
    if atm_strike_floor == trading_policy.last_strike + 5:
        #strike has moved up
        strike_moved_up = True
    elif atm_strike_ceil == trading_policy.last_strike - 5:
        #strike has moved down
        strike_moved_down = True
    strikes = list(__sim_chain_strike_series.keys())
    ms = __sim_chain_strike_series[strikes[0]][0][1]
    #print("series at e.g. strike:", __sim_chain_strike_series[strikes[0]])
    print("Trading policy 1: @ms:" + str(ms) + " Spot Price: " + str(spot_price) + " Last Spot Price: " + str(trading_policy.last_spot_price) + " Last Strike: " + str(trading_policy.last_strike) + " Strike Moved Up: " + str(strike_moved_up) + " Strike Moved Down: " + str(strike_moved_down))

    trading_policy.last_spot_price = spot_price
    trading_policy.last_chain_strike_series = __sim_chain_strike_series
    if strike_moved_up:
        trading_policy.last_strike = atm_strike_floor
    elif strike_moved_down:
        trading_policy.last_strike = atm_strike_ceil


def infer_spot_price_from_chain(chain_strike_series):
    #infer spot price as the average across each strike in chain series for strike + call mid - put mid
    spot_price = None
    total = 0
    count = 0
    actual_spot_price = None
    atm_strike, atm_diff = find_atm_strike(chain_strike_series)
    for strike in chain_strike_series:
        if strike < atm_strike - 10 or strike > atm_strike + 10:
            continue
        call_tick, call_ms = chain_strike_series[strike][0]
        put_tick, put_ms = chain_strike_series[strike][1]
        call_bid = call_tick[1]
        put_bid = put_tick[1]
        call_ask = call_tick[2]
        put_ask = put_tick[2]
        call_mid = (call_bid + call_ask) / 2
        put_mid = (put_bid + put_ask) / 2
        diff = call_mid - put_mid
        total += strike/1000 + diff
        count += 1
        actual_spot_price = call_tick[-2]
    if count > 0:
        spot_price = total / count
    return (spot_price, actual_spot_price)

def find_atm_strike(chain_strike_series):
    #given a chain_strike_series, return tuple with the strike closest to the money, and the difference between the call and put mid prices
    atm_strike = None
    atm_diff = None
    prev_atm_strike = None
    prev_atm_diff = None
    for strike in chain_strike_series:
        call_tick, call_ms = chain_strike_series[strike][0]
        put_tick, put_ms = chain_strike_series[strike][1]
        call_bid = call_tick[1]
        put_bid = put_tick[1]
        call_ask = call_tick[2]
        put_ask = put_tick[2]
        call_mid = (call_bid + call_ask) / 2
        put_mid = (put_bid + put_ask) / 2
        diff = call_mid - put_mid
        if atm_diff is None or abs(diff) < abs(atm_diff):
            if atm_strike != strike:
                prev_atm_strike = atm_strike
                prev_atm_diff = atm_diff
            atm_diff = diff
            atm_strike = strike
    
    return (atm_strike, atm_diff)

def main():
    expiration_date = "20240510"
    data = ReadData(expiration_date)
    success = data.read_data()
    if success:
        data.make_time_series()
        data.simulate_time_series()
    else:
        print("Error reading data for expiration date " + expiration_date)
    
    trading_policies = []
    trading_policy1 = TradingPolicy()
    trading_policy1.trading_policy_function = trading_policy1_function
    trading_policies.append(trading_policy1)
    trading_strategy = TradingStrategy(data.simulation_series, trading_policies)
    trading_strategy.do_simulation()

if __name__ == "__main__":
    main()