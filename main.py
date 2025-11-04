import pandas as pd 
import requests
import re
import plotly.express as px
from base64 import b64decode
import os


def decode_url(url: str) -> str:
    for _ in range(3): 
        url = b64decode(url).decode("utf-8")
    return url

def read_logs(url: str) -> pd.DataFrame:
    """
    Read logs from a URL and return a pandas DataFrame.
    """
    if os.path.exists(url):
        text = open(url).read()
    else:
        text = requests.get(url).text
    # response = requests.get(url)
    records = []
    for line in text.split("\n"):
        if not line:
            continue
        timestamp = line.split(" ")[0]
        msg = line[len(timestamp) + 1:]
        readable_timestamp = msg.split(" ")[0]
        msg = msg[len(readable_timestamp) + 1:]
        user = msg.split(" ")[0]
        msg = msg[len(user) + 1:]
        ip = msg.split(" ")[0]
        msg = msg[len(ip) + 1:]
        isp = re.search("(.+?) (online|offline)", msg).group(1)
        status = re.search("(.+?) (online|offline)", msg).group(2)
        record = {"timestamp": timestamp, "readable_timestamp": readable_timestamp, "user": user, "isp": isp, "status": status  }
        records.append(record)
    return pd.DataFrame(records)


def main():
    logs_url = decode_url("WVVoU01HTkViM1pNZWswd1RHcFZNVXhxU1hsT1V6UjVUWHBGTmsxNlFYZE5Remx6WWpKa2VrTm5QVDBLCg==")
    logs_remote = read_logs("http://34.55.225.231:3000/logs")
    # logs_local = read_logs("backup-2025-11-04-15:43.txt")
    # logs = pd.concat([logs_remote, logs_local])
    logs = logs_remote
    logs.sort_values(by="readable_timestamp", inplace=True)
    fig = px.scatter(logs, x="readable_timestamp", y="status", color="user")
    fig.show()

    for user in logs["user"].unique():
        user_logs = logs[logs["user"] == user]
        user_logs["is_offline"] = user_logs["status"] == "offline"
        user_logs["accumulated-disconnects"] = user_logs["is_offline"].cumsum(skipna=True)
        fig = px.scatter(user_logs, x="readable_timestamp", y="accumulated-disconnects", color="user")
        fig.show()

        # s: a pandas Series with a DatetimeIndex
        value = "offline"
        cond = user_logs["status"].eq(value).fillna(False)

        # label contiguous runs of True/False
        grp = (cond != cond.shift()).cumsum()

        # length of the current True-streak at each time (0 when not value)
        running_streak = cond.groupby(grp).cumsum().astype(int)
        # print(json.dumps(running_streak.to_list(), indent=4))
        counts = running_streak.value_counts().drop(0)
        if counts.empty:
            continue
        fig = px.bar(counts, x=counts.index, y=counts.values)
        x_label = "זמן ניתוק בשניות"
        y_label = "מספר ניתוקים"
        fig.update_layout(xaxis_title=x_label, yaxis_title=y_label)
        fig.show()


if __name__ == "__main__":
    main()
