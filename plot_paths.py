#read the sim_path_obj json file 
#and plot the paths
import json
import matplotlib.pyplot as plt
import numpy as np
import sys

path_plot_data = []
path_plot_data_2 = []
total_pnl = 0
total_revenue = 0
total_cost = 0
total_days = 0
total_range = 0

total_pnl_2 = 0
total_revenue_2 = 0
total_cost_2 = 0
total_days_2 = 0
total_range_2 = 0
wait_for_button_press = True
plot_separate_profit_loss = True
plot_chain = True
overlap_plot_chain = True
    
def plot_strike_path(exp, path, axs, color='g'):
    #open an output csv file
    #write the path to the csv file
    ax_0 = axs[0]
    range_low = 0
    range_high = 0
    range_low_2 = 0
    range_high_2 = 0
    global total_pnl, total_pnl_2, wait_for_button_press, total_revenue, total_cost, total_revenue_2, total_cost_2
    global total_days, total_days_2, total_range, total_range_2

    if plot_chain and overlap_plot_chain:
        if plot_separate_profit_loss:
            ax_1 = axs[1]
            ax_2 = axs[1]
        else:
            ax_1 = axs[0]
            ax_2 = axs[0]
        ax_1.clear()
        ax_2.clear()

    if not plot_separate_profit_loss or (plot_separate_profit_loss and path[-1]["revenue"] - path[-1]["cost"] >= 0):
        total_days += 1
        range_mid_path = []
        for p in path:
            if p["strike_off"] < range_low:
                range_low = p["strike_off"]
            if p["strike_off"] > range_high:
                range_high = p["strike_off"]
            range_mid_path.append((range_high+range_low)/2)
        total_range += (range_high - range_low)        
        x = [p["ms"] for p in path]
        #y = [p["strike_off"]*5/(p["revenue"]+0.01) for p in path]
        y = [p["strike_off"] for p in path]
        c = ['g' if p["revenue"]-p["cost"] > 0 else 'r' for p in path]
        txt = [f'{round(p["revenue"]),round(p["cost"]),round(p["revenue"]-p["cost"])} S/R:{round(p["revenue"]/(p["cost"]+0.01))} pf:{round(p["revenue"]-p["portfolio_value"])}' for p in path]
        path_plot_data.append((x, y, c, txt))
        ax_0.clear()
        print("txt: ", txt[-1])
        last_y = 0
        #find index for max s/r
        max_profit_index = 0
        max_running_profit_index = 0
        for i,p in enumerate(path):
            if (p["revenue"]-(p["cost"])) > (path[max_profit_index]["revenue"]-(path[max_profit_index]["cost"])):
                max_profit_index = i
            if (p["revenue"]-p["portfolio_value"]) > (path[max_running_profit_index]["revenue"]-path[max_running_profit_index]["portfolio_value"]):
                max_running_profit_index = i
        for i,item in enumerate(txt):
            if y[i] != last_y or i==max_running_profit_index or i==max_profit_index:
                annotate_color = 'orange'
                if i == max_profit_index:
                    annotate_color = 'blue'
                if i == max_running_profit_index:
                    annotate_color = 'green'
                if path[i]["revenue"]-path[i]["portfolio_value"] < 0:
                    annotate_color = 'red'
                ax_0.annotate(item, (x[i], y[i]),ha='left', rotation=30, fontsize=14, color=annotate_color)
            last_y = y[i]
        total_pnl += (path[-1]["revenue"] - path[-1]["cost"])
        total_revenue += path[-1]["revenue"]
        total_cost += path[-1]["cost"]
        print("total pnl: ", total_pnl, "total revenue: ", total_revenue, "total cost: ", total_cost, "total_days: ", total_days, "total_range: ", total_range)
        #print averages
        print("average pnl: ", total_pnl/total_days, "average revenue: ", total_revenue/total_days, "average cost: ", total_cost/total_days, "average range: ", total_range/total_days)
            #pass
        #ax.annotate(txt, (x, y))
        #ax.annotate('axes fraction',
        #        xy=(2, 1), xycoords='data',
        #        xytext=(0.36, 0.68), textcoords='axes fraction',
        #        arrowprops=dict(facecolor='black', shrink=0.05),
        #        horizontalalignment='right', verticalalignment='top')

        #make a scatter plot
        ax_0.scatter(path_plot_data[-1][0], path_plot_data[-1][1], color=path_plot_data[-1][2], s=10)
        ax_0.scatter(path_plot_data[-1][0], range_mid_path, color='magenta', s=10)

        ax_0.plot(path_plot_data[-1][0], path_plot_data[-1][1], color=path_plot_data[-1][2][-1], linewidth=2)
        ax_0.text(path_plot_data[-1][0][-1], path_plot_data[-1][1][-1], txt[-1], fontsize=24)
        ax_0.set_title(exp)
    
    if plot_separate_profit_loss and plot_chain:
        if overlap_plot_chain:
            ax_3 = axs[1]
        else:
            ax_3 = axs[3]
    elif plot_separate_profit_loss and not plot_chain:
        ax_3 = axs[1]
    if plot_separate_profit_loss and path[-1]["revenue"] - path[-1]["cost"] < 0:
        total_days_2 += 1
        range_mid_path_2 = []
        for p in path:
            if p["strike_off"] < range_low_2:
                range_low_2 = p["strike_off"]
            if p["strike_off"] > range_high_2:
                range_high_2 = p["strike_off"]
            range_mid_path_2.append((range_high_2+range_low_2)/2)
        total_range_2 += (range_high_2 - range_low_2)
        x_2 = [p["ms"] for p in path]
        #y = [p["strike_off"]*5/(p["revenue"]+0.01) for p in path]
        y_2 = [p["strike_off"] for p in path]
        c_2 = ['g' if p["revenue"]-p["cost"] > 0 else 'r' for p in path]
        txt_2 = [f'{round(p["revenue"],1),round(p["cost"],2)} S/R:{round(p["revenue"]/(p["cost"]+0.01),1)} pf:{round(p["revenue"]-p["portfolio_value"])}' for p in path]
        path_plot_data_2.append((x_2, y_2, c_2, txt_2))
        ax_3.clear()
        print("txt_2: ", txt_2[-1])
        last_y_2 = 0
        max_profit_index = 0
        max_running_profit_index = 0
        for i,p in enumerate(path):
            if (p["revenue"]-(p["cost"])) > (path[max_profit_index]["revenue"]-(path[max_profit_index]["cost"])):
                max_profit_index = i
            if (p["revenue"]-p["portfolio_value"]) > (path[max_running_profit_index]["revenue"]-path[max_running_profit_index]["portfolio_value"]):
                max_running_profit_index = i
        for i,item in enumerate(txt_2):
            if y_2[i] != last_y_2 or i==max_running_profit_index or i==max_profit_index:
                annotate_color = 'orange'
                if i == max_profit_index:
                    annotate_color = 'blue'
                if i == max_running_profit_index:
                    annotate_color = 'green'
                if path[i]["revenue"]-path[i]["portfolio_value"] < 0:
                    annotate_color = 'red'
                ax_3.annotate(item, (x_2[i], y_2[i]),ha='left', rotation=30, fontsize=14, color=annotate_color)
            last_y_2 = y_2[i]
        total_pnl_2 += (path[-1]["revenue"] - path[-1]["cost"])
        total_revenue_2 += path[-1]["revenue"]
        total_cost_2 += path[-1]["cost"]
        print("total pnl_2: ", total_pnl_2, "total revenue_2: ", total_revenue_2, "total cost_2: ", total_cost_2, "total_days_2: ", total_days_2, "total_range_2: ", total_range_2)
        print("average pnl_2: ", total_pnl_2/total_days_2, "average revenue_2: ", total_revenue_2/total_days_2, "average cost_2: ", total_cost_2/total_days_2, "average range_2: ", total_range_2/total_days_2)
            #pass
        #ax.annotate(txt, (x, y))
        #ax.annotate('axes fraction',
        #        xy=(2, 1), xycoords='data',
        #        xytext=(0.36, 0.68), textcoords='axes fraction',
        #        arrowprops=dict(facecolor='black', shrink=0.05),
        #        horizontalalignment='right', verticalalignment='top')

        #make a scatter plot
        ax_3.scatter(path_plot_data_2[-1][0], path_plot_data_2[-1][1], color=path_plot_data_2[-1][2], s=10)
        ax_3.scatter(path_plot_data_2[-1][0], range_mid_path_2, color='magenta', s=10)

        ax_3.plot(path_plot_data_2[-1][0], path_plot_data_2[-1][1], color=path_plot_data_2[-1][2][-1], linewidth=2)
        ax_3.text(path_plot_data_2[-1][0][-1], path_plot_data_2[-1][1][-1], txt_2[-1], fontsize=24)
        ax_3.set_title(exp)

    #plot the chain for each point in the path on ax_1
    if plot_chain:
        if not overlap_plot_chain:
            ax_1 = axs[1]
            ax_1.clear()
            ax_2 = axs[2]
            ax_2.clear()
        else:
            if plot_separate_profit_loss:
                ax_1 = axs[1]
                ax_2 = axs[1]
                
            else:
                ax_1 = axs[0]
                ax_2 = axs[0]
                
        strike_off_min = 0
        strike_off_max = 0
        call_chain_y = {}
        put_chain_y = {}
        call_chain_x = {}
        put_chain_x = {}
        chain_length = 29
        last_revenue = 0
        mark_trades = {}
        for p in path:
            if p["strike_off"] < strike_off_min:
                strike_off_min = p["strike_off"]
            if p["strike_off"] > strike_off_max:
                strike_off_max = p["strike_off"]
            
            if p["revenue"] > last_revenue:
                last_revenue = p["revenue"]
                mark_trades[p["ms"]] = (True, p["strike_off"])
            else:
                mark_trades[p["ms"]] = (False, p["strike_off"])
            #print("p: ", p)
            assert len(p["chain"]) == chain_length
            for chain_strike_off in range(-70,75,5):
                chain_strike_off += p["strike_off"]
                if chain_strike_off not in call_chain_y:
                    call_chain_y[chain_strike_off] = []
                    call_chain_x[chain_strike_off] = []
                    put_chain_y[chain_strike_off] = []
                    put_chain_x[chain_strike_off] = []
                strike_matched_in_chain = False
                for [strike_off_in_chain,call_mid,put_mid] in p["chain"]:
                    if strike_off_in_chain == chain_strike_off:
                        strike_matched_in_chain = True
                        #print("strike_off_in_chain: ", strike_off_in_chain, "chain_strike_off: ", chain_strike_off, "call_mid: ", call_mid, "put_mid: ", put_mid)
                        call_chain_y[chain_strike_off].append(call_mid)
                        call_chain_x[chain_strike_off].append(p["ms"])
                        put_chain_y[chain_strike_off].append(put_mid)
                        put_chain_x[chain_strike_off].append(p["ms"])
                        break
                #if not strike_matched_in_chain:
                #    call_chain_y[chain_strike_off-p["strike_off"]].append(0)
                #    put_chain_y[chain_strike_off-p["strike_off"]].append(0)
                #    print("strike not matched in chain: ", chain_strike_off, "p: ", p)
                #    exit(1)
        #print("len(call_chain_y[chain_strike_off-p['strike_off']]): ", len(call_chain_y[chain_strike_off-p["strike_off"]]), "chain_strike_off: ", chain_strike_off-p["strike_off"], "len(path_plot_data[-1][0]): ", len(path_plot_data[-1][0]))
        #assert len(call_chain_y[chain_strike_off-p["strike_off"]]) == len(path_plot_data[-1][0])
        #assert len(put_chain_y[chain_strike_off-p["strike_off"]]) == len(path_plot_data[-1][0])
        for chain_strike_off in call_chain_y:
            #plot only between strike_off_min and strike_off_max
            if chain_strike_off < strike_off_min or chain_strike_off > strike_off_max:
                continue
            #print("chain_strike_off: ", chain_strike_off, "x=", call_chain_x[chain_strike_off], "y=",call_chain_y[chain_strike_off], "strike_off_min: ", strike_off_min, "strike_off_max: ", strike_off_max)
            if call_chain_x[chain_strike_off] != [] and call_chain_y[chain_strike_off] != []:
                call_start_x = 0
                for i in range(len(call_chain_x[chain_strike_off])):
                    if mark_trades[call_chain_x[chain_strike_off][i]][0] and mark_trades[call_chain_x[chain_strike_off][i]][1] == chain_strike_off:
                        ax_1.scatter(call_chain_x[chain_strike_off][i], call_chain_y[chain_strike_off][i], color='green', s=30)
                        call_start_x = i
                ax_1.plot(call_chain_x[chain_strike_off][call_start_x:], call_chain_y[chain_strike_off][call_start_x:], color='blue', linewidth=1)
                ax_1.text(call_chain_x[chain_strike_off][0], call_chain_y[chain_strike_off][0], str(chain_strike_off), fontsize=10)
                ax_1.text(call_chain_x[chain_strike_off][-1], call_chain_y[chain_strike_off][-1], str(chain_strike_off), fontsize=10)
            if put_chain_x[chain_strike_off] != [] and put_chain_y[chain_strike_off] != []:
                put_start_x = 0
                for i in range(len(put_chain_x[chain_strike_off])):
                    if mark_trades[put_chain_x[chain_strike_off][i]][0] and mark_trades[put_chain_x[chain_strike_off][i]][1] == chain_strike_off:
                        ax_2.scatter(put_chain_x[chain_strike_off][i], put_chain_y[chain_strike_off][i], color='green', s=30)
                        put_start_x = i
                ax_2.plot(put_chain_x[chain_strike_off][put_start_x:], put_chain_y[chain_strike_off][put_start_x:], color='orange', linewidth=1)
                ax_2.text(put_chain_x[chain_strike_off][0]-10000, put_chain_y[chain_strike_off][0], str(chain_strike_off), fontsize=10)
                ax_2.text(put_chain_x[chain_strike_off][-1]+10000, put_chain_y[chain_strike_off][-1], str(chain_strike_off), fontsize=10)
                
               
    #unhighlight older paths
    for i in range(len(path_plot_data)-1):
        ax_0.scatter(path_plot_data[i][0], path_plot_data[i][1], color=path_plot_data[i][2], s=3)
        ax_0.plot(path_plot_data[i][0], path_plot_data[i][1], color=path_plot_data[i][2][-1], linewidth=0.5)

    if plot_separate_profit_loss:
        for i in range(len(path_plot_data_2)-1):
            ax_3.scatter(path_plot_data_2[i][0], path_plot_data_2[i][1], color=path_plot_data_2[i][2], s=3)
            ax_3.plot(path_plot_data_2[i][0], path_plot_data_2[i][1], color=path_plot_data_2[i][2][-1], linewidth=0.5)    
    #show values at each point
    #sleep for 10s
    #pause until keyboard is pressed
    try:
        while wait_for_button_press:
            plt.pause(0.1)
            if plt.waitforbuttonpress():
                break
    except KeyboardInterrupt:
        wait_for_button_press = False
    #plt.pause(0.1)    



def plot_path_obj(fig, path_obj, axs):
    for exp in path_obj:
        print("exp: ", exp)
        plot_strike_path(exp,path_obj[exp], axs)
    ax_0 = axs[0]
    ax_0.set_xlabel("Time")
    ax_0.set_ylabel("Strike_off")
    ax_0.grid()
    ax_0.legend()
    if plot_separate_profit_loss:
        if plot_chain:
            if overlap_plot_chain:
                ax_3 = axs[1]
            else:
                ax_3 = axs[3]
        else:
            ax_3 = axs[1]
        ax_3.set_xlabel("Time")
        ax_3.set_ylabel("Strike_off")
        ax_3.grid()
        ax_3.legend()


def main():
    if len(sys.argv) < 2:
        print("Usage: %s <path_obj.json>" % sys.argv[0])
        sys.exit(1)

    path_obj_file = sys.argv[1]
    with open(path_obj_file, 'r') as f:
        path_obj = json.load(f)
    num_plots = 0
    if plot_chain:
        if overlap_plot_chain:
            num_plots += 0
        else:
            num_plots += 2
    if plot_separate_profit_loss:
        num_plots += 2
    else:
        num_plots += 1
    fig, axs = plt.subplots(num_plots,1,figsize=(35, 20),sharex=True)
    fig.subplots_adjust(hspace=0)
    plot_path_obj(fig, path_obj, axs)
    plt.show()

if __name__ == "__main__":
    main()