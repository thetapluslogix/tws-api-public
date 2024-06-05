#historical greek data analyzer. reads json data files, analyzes them, and displays data on a web dashboard
import json
from math import ceil, floor
import os
import sys
import re
from datetime import datetime, timedelta, timezone
import concurrent.futures
import time
from datetime import datetime
import math

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
        self.data_type = "bulk_historical_quote"
        self.ticker = "SPXW"
        self.expiration_date = expiration_date
        self.start_date = expiration_date
        self.end_date = expiration_date
        self.expiration_date = expiration_date
        self.ticker = "SPXW"
        self.data_type = "bulk_historical_quote"
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
            #print("At time: " + str(ms_key))
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
            
            inferred_spot_price = infer_spot_price_from_chain(self.chain_strike_series)
           
            #print("@ms:" + str(ms_key) + " Inferred Spot Price: " + str(inferred_spot_price))
            _chain_strike_series = {}
            for strike in self.chain_strike_series:
                adj_strike = strike/1000
                call_tick, call_ms_key = self.chain_strike_series[strike][0]
                put_tick, put_ms_key = self.chain_strike_series[strike][1]
                _chain_strike_series[adj_strike] = [(call_tick,call_ms_key), (put_tick, put_ms_key)]
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
    def __init__(self, expiration_date):
        self.last_spot_price = None
        self.last_chain_strike_series = None
        self.last_strike = None
        self.positions = {} #key is strike, value is [] of (time, count, strike, right, price) tuples
        self.trades = [] #list of (time, count, strike, right, price) tuples
        self.trading_policy_function = None
        self.total_revenue = 0
        self.total_cost = 0
        self.start_strike = None
        self.path_over_time = []
        self.trades_at_current_time = []
        self.chain_at_current_time = []
        self.expiration_date = expiration_date
        self.name = None
        self.chain_wing_width = 70
        self.current_portfolio_value = 0

        
        
    def do_trading(self, _sim_chain_strike_series, spot_price):
        self.trading_policy_function(self, _sim_chain_strike_series, spot_price)
    def make_trade(self, time, count, strike, right, price):
        self.trades.append((time, count, strike, right, price))
        if strike not in self.positions:
            self.positions[strike] = []
        self.positions[strike].append((time, count, strike, right, price))
        self.total_revenue -= count * price
        self.trades_at_current_time.append((count, strike-self.start_strike, right, price))
    def convert_ms_to_datetime(self, ms):
        return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(timezone(timedelta(hours=-3))).strftime('%H:%M:%S')

def trading_policy1_function(trading_policy,__sim_chain_strike_series, spot_price):
    trading_policy.trades_at_current_time = []
    trading_policy.chain_at_current_time = []
    #print("Trading policy 1: Chain Strike Series: " + str(chain_strike_series) + " Spot Price: " + str(spot_price))
    atm_strike_floor = floor(spot_price/5)*5
    atm_strike_ceil = ceil(spot_price/5)*5

    if trading_policy.last_spot_price is None:
        trading_policy.last_spot_price = spot_price
        trading_policy.last_chain_strike_series = __sim_chain_strike_series
        trading_policy.last_strike = atm_strike_floor
        trading_policy.start_strike = atm_strike_floor
        return
    strike_moved_up = False
    strike_moved_down = False
    new_strike = trading_policy.last_strike
    if atm_strike_floor == trading_policy.last_strike + 5:
        #strike has moved up
        strike_moved_up = True
        new_strike = atm_strike_floor
    elif atm_strike_ceil == trading_policy.last_strike - 5:
        #strike has moved down
        strike_moved_down = True
        new_strike = atm_strike_ceil
    strikes = list(__sim_chain_strike_series.keys())
    ms = __sim_chain_strike_series[strikes[0]][0][1]
    if strike_moved_up or strike_moved_down:
        call_mid_price = (__sim_chain_strike_series[new_strike][0][0][3] + __sim_chain_strike_series[new_strike][0][0][7]) / 2
        put_mid_price = (__sim_chain_strike_series[new_strike][1][0][3] + __sim_chain_strike_series[new_strike][1][0][7]) / 2
        straddle_price = call_mid_price + put_mid_price
        pdt_time = trading_policy.convert_ms_to_datetime(ms)
        print(f"Trading policy 1: @hr:m:s {pdt_time} strike: {new_strike} straddle_price: {straddle_price} Strike Moved Up: {strike_moved_up} Strike Moved Down: {strike_moved_down}")
        total_cost = 0
        total_positions = 0
        range_lower_bound = None
        range_upper_bound = None
        range_size = 0
        strike_in_range_perc = 0
        hedge_cost_at_s = 0
        hedge_cost_at_onehalf_s = 0
        hedge_cost_at_two_s = 0
               
        can_open_short_call_position = True
        can_open_short_put_position = True    
        for position_strike in trading_policy.positions:
            for position in trading_policy.positions[position_strike]:
                #unpack position
                time, count, strike, right, price = position
                assert strike == position_strike
                if right == 'C':
                    if strike == new_strike and count < 0:
                        can_open_short_call_position = False
                if right == 'P':
                    if strike == new_strike and count < 0:
                        can_open_short_put_position = False
        if can_open_short_call_position:
            #open a short position
            trading_policy.make_trade(ms, -1, new_strike, 'C', call_mid_price)
            print(f"Opened short call position at strike {new_strike} with price {call_mid_price}")
        if can_open_short_put_position:
            #open a short position
            trading_policy.make_trade(ms, -1, new_strike, 'P', put_mid_price)
            print(f"Opened short put position at strike {new_strike} with price {put_mid_price}")

        total_value_at_current_time = 0
        #print positions
        for position_strike in trading_policy.positions:
            for position in trading_policy.positions[position_strike]:
                time, count, strike, right, price = position
                assert strike == position_strike
                if right == 'C' and strike < new_strike:
                    total_cost -= count * (new_strike - strike)
                if right == 'P' and strike > new_strike:
                    total_cost -= count * (strike - new_strike)
                total_positions -= count
                if range_lower_bound is None or strike < range_lower_bound:
                    range_lower_bound = strike
                if range_upper_bound is None or strike > range_upper_bound:
                    range_upper_bound = strike
                assert ms == __sim_chain_strike_series[strike][0][1]
                current_position_value = 0
                if right == 'C':
                    current_position_value = count * (__sim_chain_strike_series[strike][0][0][3] + __sim_chain_strike_series[strike][0][0][7]) / 2
                if right == 'P':
                    current_position_value = count * (__sim_chain_strike_series[strike][1][0][3] + __sim_chain_strike_series[strike][1][0][7]) / 2
                total_value_at_current_time -= current_position_value
                trading_policy.current_portfolio_value = total_value_at_current_time
                print(f"    Position: Time: {trading_policy.convert_ms_to_datetime(time)} Count: {count} Strike: {strike} Right: {right} Price: {price}", "Total Cost: ", total_cost, "new_strike: ", new_strike, "total_value_at_current_time: ", total_value_at_current_time)
                
        
        #print total revenue and cost
        av_revenue = trading_policy.total_revenue / total_positions if total_positions != 0 else 0
        if range_lower_bound is not None and range_upper_bound is not None:
            range_size = range_upper_bound - range_lower_bound
            strike_in_range_perc = (new_strike - range_lower_bound)*100/range_size if range_size != 0 else 0
            r_by_s = range_size / (2*av_revenue) if av_revenue != 0 else 0
        #find hedge cost at s, 1.5s, 2s
        if range_lower_bound is not None and range_upper_bound is not None:
            call_strike_at_s = floor((range_lower_bound + 2*av_revenue)/5)*5
            put_strike_at_s = ceil((range_upper_bound - 2*av_revenue)/5)*5
            call_strike_at_onehalf_s = floor((range_lower_bound + 1.5*2*av_revenue)/5)*5
            put_strike_at_onehalf_s = ceil((range_upper_bound - 1.5*2*av_revenue)/5)*5
            call_strike_at_two_s = floor((range_lower_bound + 2*2*av_revenue)/5)*5
            put_strike_at_two_s = ceil((range_upper_bound - 2*2*av_revenue)/5)*5
            call_hedge_cost_at_s = (__sim_chain_strike_series[call_strike_at_s][0][0][3] + __sim_chain_strike_series[call_strike_at_s][0][0][7]) / 2
            put_hedge_cost_at_s = (__sim_chain_strike_series[put_strike_at_s][1][0][3] + __sim_chain_strike_series[put_strike_at_s][1][0][7]) / 2
            call_hedge_cost_at_onehalf_s = (__sim_chain_strike_series[call_strike_at_onehalf_s][0][0][3] + __sim_chain_strike_series[call_strike_at_onehalf_s][0][0][7]) / 2
            put_hedge_cost_at_onehalf_s = (__sim_chain_strike_series[put_strike_at_onehalf_s][1][0][3] + __sim_chain_strike_series[put_strike_at_onehalf_s][1][0][7]) / 2
            call_hedge_cost_at_two_s = (__sim_chain_strike_series[call_strike_at_two_s][0][0][3] + __sim_chain_strike_series[call_strike_at_two_s][0][0][7]) / 2
            put_hedge_cost_at_two_s = (__sim_chain_strike_series[put_strike_at_two_s][1][0][3] + __sim_chain_strike_series[put_strike_at_two_s][1][0][7]) / 2
        print(f"    Total Revenue: {trading_policy.total_revenue} Total Cost: {total_cost}", "Average Revenue: ", av_revenue, "Range Size: ", range_size, "Strike in Range %: ", strike_in_range_perc, "R by S: ", r_by_s, "range_low:", range_lower_bound, "range_high:", range_upper_bound)
        trading_policy.total_cost = total_cost

        #print hedge costs
        if range_lower_bound is not None and range_upper_bound is not None:
            print(f"    Hedge Cost at 1*s: {call_hedge_cost_at_s} @{call_strike_at_s}  {put_hedge_cost_at_s} @{put_strike_at_s} Hedge Cost at 1.5*s: {call_hedge_cost_at_onehalf_s} @{call_strike_at_onehalf_s} {put_hedge_cost_at_onehalf_s} @{put_strike_at_onehalf_s} Hedge Cost at 2*s: {call_hedge_cost_at_two_s} @{call_strike_at_two_s} {put_hedge_cost_at_two_s} @{put_strike_at_two_s}")
        
        trading_policy.last_spot_price = spot_price
        trading_policy.last_chain_strike_series = __sim_chain_strike_series
        trading_policy.last_strike = new_strike
    #populate chain at current time
    for range_strike in range(trading_policy.start_strike-trading_policy.chain_wing_width,trading_policy.start_strike+trading_policy.chain_wing_width+5,5):
        if range_strike not in __sim_chain_strike_series:
            continue
        assert ms == __sim_chain_strike_series[range_strike][0][1]
        call_mid_price = (__sim_chain_strike_series[range_strike][0][0][3] + __sim_chain_strike_series[range_strike][0][0][7]) / 2
        put_mid_price = (__sim_chain_strike_series[range_strike][1][0][3] + __sim_chain_strike_series[range_strike][1][0][7]) / 2
        trading_policy.chain_at_current_time.append((range_strike - trading_policy.start_strike, call_mid_price, put_mid_price))
    #update path node info
    path_node_info_obj_val = {"ms":ms, "strike_off": round(trading_policy.last_strike-trading_policy.start_strike, 2), "revenue": round(trading_policy.total_revenue, 2), "cost": round(trading_policy.total_cost, 2), "trades": trading_policy.trades_at_current_time, "chain": trading_policy.chain_at_current_time, "portfolio_value": trading_policy.current_portfolio_value}
    trading_policy.path_over_time.append(path_node_info_obj_val)
    print("Exp:", trading_policy.expiration_date, "Path node info: ", path_node_info_obj_val)
    


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
        call_bid = call_tick[3]
        put_bid = put_tick[3]
        call_ask = call_tick[7]
        put_ask = put_tick[7]
        call_mid = (call_bid + call_ask) / 2
        put_mid = (put_bid + put_ask) / 2
        diff = call_mid - put_mid
        total += strike/1000 + diff
        count += 1
        #actual_spot_price = call_tick[-2]
    if count > 0:
        spot_price = total / count
    return spot_price

def find_atm_strike(chain_strike_series):
    #given a chain_strike_series, return tuple with the strike closest to the money, and the difference between the call and put mid prices
    atm_strike = None
    atm_diff = None
    prev_atm_strike = None
    prev_atm_diff = None
    for strike in chain_strike_series:
        call_tick, call_ms = chain_strike_series[strike][0]
        put_tick, put_ms = chain_strike_series[strike][1]
        call_bid = call_tick[3]
        put_bid = put_tick[3]
        call_ask = call_tick[7]
        put_ask = put_tick[7]
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
    sim_path_obj = {}
    data_type = "bulk_historical_quote"
    ticker = "SPXW"
    directory = "C:\\Thetadata\\" + data_type + "\\" + ticker + "\\"
    #expiration dates are the directories in the directory containing at least one json file
    expiration_dates = []
    for root, dirs, files in os.walk(directory):
        for dir in dirs:
            if len(os.listdir(directory + dir)) > 0:
                expiration_dates.append(dir)
    #launch a thread pool to analyze data for each expiration date
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        expiration_date_to_future = {executor.submit(analyze_data, expiration_date): expiration_date for expiration_date in expiration_dates}
        for future in concurrent.futures.as_completed(expiration_date_to_future):
            expiration_date = expiration_date_to_future[future]
            try:
                path_over_time = future.result()
                sim_path_obj[expiration_date] = path_over_time
            except Exception as e:
                print("Error analyzing data for expiration date " + expiration_date + ": " + str(e) + "type:" + str(type(e)))
                exit(1)
    sim_path_obj_str = json.dumps(sim_path_obj)
    #print("sim path obj:", sim_path_obj_str)
    #write sim path obj as a json file in the directory pointed to by directory
    with open(directory + "sim_path_obj.json", "w") as f:
        print("Writing sim path obj to file: size of sim path obj: " + str(len(sim_path_obj_str)) + " bytes")
        f.write(sim_path_obj_str)

def analyze_data(expiration_date):
    print("*******************************************************")
    print("Analyzing data for expiration date " + expiration_date)
    data = ReadData(expiration_date)
    success = data.read_data()
    if success:
        data.make_time_series()
        data.simulate_time_series()
    else:
        print("Error reading data for expiration date " + expiration_date)
        
    trading_policies = []
    trading_policy1 = TradingPolicy(expiration_date)
    trading_policy1.trading_policy_function = trading_policy1_function
    trading_policies.append(trading_policy1)
    trading_strategy = TradingStrategy(data.simulation_series, trading_policies)
    trading_strategy.do_simulation()
    return trading_policy1.path_over_time
if __name__ == "__main__":
    main()