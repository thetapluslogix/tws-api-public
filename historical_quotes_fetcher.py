#using the documentation at https://http-docs.thetadata.us/docs/theta-data-rest-api-v2/4g9ms9h4009k0-getting-started
#download SPXW option historical greek bulk snapshot data for a given expiration date starting from a given date

import requests
import json
import pandas as pd
import os
from datetime import datetime
import threading
import concurrent.futures

class ThetaDataRequester(threading.Thread):
    def __init__(self, expiration_date:str):
        threading.Thread.__init__(self)
        self.start_date = expiration_date
        self.end_date = expiration_date
        self.expiration_date = expiration_date
        self.ticker = "SPXW"
        self.data_type = "bulk_historical_quote"
        self.ivl = 60000
        self.page_num = 0
        self.url = "http://127.0.0.1:25510/v2/bulk_hist/option/quote"
        self.output_path = "C:\\Thetadata\\" + self.data_type + "\\" + self.ticker + "\\" + self.expiration_date + "\\"
        #create the output path if it does not exist
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        print("Fetching data for " + self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date)
        

    def fetch_data(self):
        page_is_valid = True
        successful_fetch = True
        if os.path.exists(self.output_path + self.ticker + "_" + self.data_type + "_" + self.expiration_date + "_" + self.start_date + "_" + str(self.ivl) + "_" + str(self.page_num) + ".json"):
            print("Data already fetched for " + self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date)
            return (successful_fetch, 200)
                 
        while page_is_valid:
            response = None
            if self.page_num == 0:
                url = self.url
                headers = {
                    "Content-Type": "application/json"
                }
                querystring = "{" + f'"exp":"{self.expiration_date}", "start_date":"{self.start_date}", "end_date":"{self.end_date}", "root":"{self.ticker}", "ivl":{self.ivl}' + "}"
                query_json = json.loads(querystring)
                response = requests.get(url, headers=headers, params=query_json)
            else:
                response = requests.get(self.url)
            
            if response.status_code == 200:
                response_json = response.json()
                #write json response to a file
                with open(self.output_path + self.ticker + "_" + self.data_type + "_" + self.expiration_date + "_" + self.start_date + "_" + str(self.ivl) + "_" + str(self.page_num) + ".json", "w") as f:
                    json.dump(response_json, f)
                print(self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date + " fetched successfully")
                next_page = response_json["header"]["next_page"]
                
                #check if there are more pages to fetch
                if next_page == "null":
                    page_is_valid = False
                else:
                    self.page_num += 1
                    self.url = next_page
            else:
                print("Error fetching data for " + self.ticker + " " + self.data_type + " for expiration date " + self.expiration_date + " on " + self.start_date)
                print("     Status code: " + str(response.status_code), "Response: " + response.text)
                page_is_valid = False
                successful_fetch = False
                break
        return (successful_fetch, response.status_code)
            
def main():
    #expiration_dates = ["20240506", "20240507", "20240508", "20240509", "20240510"]
    expiration_dates = []
    #get the expiration dates for all of 2023 and 2024 until May 10, 2024. The expiration dates are string in the format yyyymmdd. Exclude saturdays and sundays.
    for year in range(2023, 2025):
        for month in range(1, 13):
            for day in range(1, 32):
                try:
                    if datetime(year, month, day) > datetime(2024, 6, 3):
                        break
                    if datetime(year, month, day).weekday() == 5 or datetime(year, month, day).weekday() == 6:
                        continue
                    expiration_date = datetime(year, month, day).strftime("%Y%m%d")
                    expiration_dates.append(expiration_date)
                except:
                    pass
    succsessful_fetch_count = 0
    total_fetch_count = 0
    succsessful_fetches = []
    #create a threadpoolexecutor to fetch data for each expiration date
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        td_requesters = [ ThetaDataRequester(expiration_date) for expiration_date in expiration_dates ]
        fetch_results_tuple = executor.map(lambda td_requester: td_requester.fetch_data(), td_requesters)
        for fetch_succsess_status, response_status_code in fetch_results_tuple:
            total_fetch_count += 1
            if fetch_succsess_status:
                succsessful_fetch_count += 1
            else:
                print("Failed fetch for expiration date " + expiration_dates[total_fetch_count - 1] + " with status code " + str(response_status_code))
    print("Total fetches: " + str(total_fetch_count), "Successful fetches: " + str(succsessful_fetch_count), "Failed fetches: " + str(total_fetch_count - succsessful_fetch_count))
if __name__ == "__main__":
    main()