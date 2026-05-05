import datetime

expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
now = datetime.datetime.now(datetime.timezone.utc)

print(f"now: {now}")
print(f"expires_at: {expires_at}")
print(f"now < expires_at: {now < expires_at}")
