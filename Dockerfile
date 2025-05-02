FROM python:3.10

COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt

RUN apt-get update && apt-get install -y cron
RUN mkdir -p /app/data/logs
RUN echo '#!/bin/bash\npython refresh_catalog.py > /app/data/logs/output.log 2>&1' > /app/run_refresh.sh && chmod +x /app/run_refresh.sh
RUN echo "1 3 * * * /usr/local/bin/python /app/cadence.py > /app/data/logs/cadence_log.txt 2>&1" >> /etc/cron.d/cadence_job && \
    echo "1 4 * * * /usr/local/bin/python /app/flares.py > /app/data/logs/flares_log.txt 2>&1" >> /etc/cron.d/flares_job
RUN chmod 0644 /etc/cron.d/cadence_job /etc/cron.d/flares_job
RUN touch /var/log/cron.log

CMD bash -c "cron && tail -f /var/log/cron.log & python /app/trigger.py"