import datetime

try:
    from systemd import journal
except:
    print('Failed to import systemd.journal')

def load_logs():
    try:
        j = journal.Reader()

        
        j.add_match(_SYSTEMD_UNIT="sharp.service")

        j.seek_head()

        entries = []
        n = 1

        for entry in j:
            timestamp = datetime.datetime.fromtimestamp(entry['__REALTIME_TIMESTAMP'].timestamp())
            msg = entry["MESSAGE"]
            date = timestamp.strftime('%d/%m/%y')
            time = timestamp.strftime('%I:%M:%S%p')
            data = (n, date, time, msg)
            entries.append(data)
            n += 1

        entries.reverse()

        return entries
    except:
        return None
