# Base model
FROM python:3.11-slim

#Рабочая папка внутри контейнера
WORKDIR /myhh

#Копируем сначала зависимости, чтобы закешировать слои
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

#Копируем остальной код парсера
COPY . .

# RUN COMMAND
CMD [ "python3","main.py" ]

