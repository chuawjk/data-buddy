import pandas as pd

df = pd.read_csv("data/customers_q3.csv")
churn_rate = df["churned"].mean()
print(f"Overall churn rate: {churn_rate:.1%}")
