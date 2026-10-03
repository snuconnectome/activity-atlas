"""Calendar weeks, retaining zero-activity weeks inside an observed interval."""
from datetime import datetime, timedelta, timezone


def week_key(stamp):
    d=datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(timezone.utc)
    year,week,_=d.isocalendar()
    return f'{year}-W{week:02d}'


def calendar_weeks(start, end):
    start=datetime.fromisoformat(start.replace('Z','+00:00')).astimezone(timezone.utc)
    end=datetime.fromisoformat(end.replace('Z','+00:00')).astimezone(timezone.utc)
    current=start-timedelta(days=start.weekday())
    last=end-timedelta(days=end.weekday())
    current=current.replace(hour=0,minute=0,second=0,microsecond=0)
    last=last.replace(hour=0,minute=0,second=0,microsecond=0)
    result=[]
    while current<=last:
        result.append(week_key(current.isoformat()));current+=timedelta(days=7)
    return result
