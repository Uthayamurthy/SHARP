'''
S.H.A.R.P - Smart Home Automation Research Project

    Copyright (C) 2024  R Uthaya Murthy

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

Contact Author : uthayamurthy2006@gmail.com
'''

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
