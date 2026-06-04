import pandas as pd

df = pd.read_csv("data/customers_q3.csv")
churn_by_plan = df.groupby("plan_tier")["churned"].mean()
print(churn_by_plan)
