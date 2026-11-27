import requests
import html
import re
import psycopg2
import os
import pandas as pd
import time
from datetime import date, timedelta
from random import randint
from sqlalchemy import create_engine

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import *

import traceback
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.environ.get('TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
ONE_HOUR = 3600

def send_text(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}

    requests.post(url,data=payload,timeout=10)
def telegram_bot(df_jobs):
    # text = df_jobs.iloc[:].to_string()
    # print(text)
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        for _, job in df_jobs.iterrows():
            vacancy = []
            vacancy.append(f"{job['title']} (ID: {job['id']})")
            vacancy.append(f"{job['url']}")
            vacancy.append(f"Компания: {job['company']}")
            vacancy.append(f"Зарплата: {job['salary']}")
            vacancy.append(f"Опыт: {job['experience']}")
            vacancy.append(f"График: {job['schedule']}, {job['employment']}")
            vacancy = "\n".join(vacancy)

            payload = {"chat_id": CHAT_ID, "text": vacancy}
            response = requests.post(url,data=payload,timeout=10)
            if response.status_code != 200:
                print(f'API ERROR: {response.status_code} {response.text}')
    except:
        print(f"Ошибка: {type(e).__name__}: {e}")
        traceback.print_exc()
def parse_hh_raw_page(raw_html):
    clean_text = html.unescape(raw_html)
    chunks = clean_text.split('"vacancyId":')

    vacancies = []

    exp_map = {
        "noExperience": "Без опыта",
        "between1And3": "От 1 года до 3 лет",
        "between3And6": "От 3 до 6 лет",
        "moreThan6": "Более 6 лет"
    }
    schedule_map = {
        "fullDay": "Полный день",
        "remote": "Удаленная работа",
        "flexible": "Гибкий график",
        "shift": "Сменный график",
        "flyInFlyOut": "Вахтовый метод"
    }
    emp_map = {
        "FULL": "Полная занятость",
        "PART": "Частичная занятость",
        "PROJECT": "Проектная работа",
        "PROBATION": "Стажировка"
    }

    for i in range(1, len(chunks)):
        chunk = chunks[i]       
        prev_chunk = chunks[i-1] 
        
        # 1. ID вакансии
        v_id_match = re.match(r'^(\d+)', chunk)
        vacancy_id = v_id_match.group(1) if v_id_match else "Неизвестно"
        
        # 2. Ссылка на вакансию (формируется на основе ID)
        vacancy_url = f"https://hh.ru/vacancy/{vacancy_id}" if vacancy_id != "Неизвестно" else "Ссылка недоступна"
        
        # 3. Название вакансии
        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', chunk)
        name = name_match.group(1) if name_match else "Не указано"
        
        # 4. Компания 
        company_match = re.search(r'"company"\s*:\s*\{.{0,300}?"name"\s*:\s*"([^"]+)"', chunk)
        company = company_match.group(1) if company_match else "Не указано"
        
        # 5. Зарплата
        salary_match = re.search(r'"compensation"\s*:\s*(\{.*?\})', chunk)
        salary = "Не указана"
        if salary_match:
            comp_data = salary_match.group(1)
            if "noCompensation" not in comp_data:
                s_from = re.search(r'"from"\s*:\s*(\d+)', comp_data)
                s_to = re.search(r'"to"\s*:\s*(\d+)', comp_data)
                curr = re.search(r'"currency"\s*:\s*"([^"]+)"', comp_data)
                
                v_from = s_from.group(1) if s_from else ""
                v_to = s_to.group(1) if s_to else ""
                v_curr = curr.group(1) if curr else "руб."
                
                if v_from and v_to:
                    salary = f"от {v_from} до {v_to} {v_curr}"
                elif v_from:
                    salary = f"от {v_from} {v_curr}"
                elif v_to:
                    salary = f"до {v_to} {v_curr}"

        # 6. Требуемый опыт
        exp_match = re.search(r'"workExperience"\s*:\s*"([^"]+)"', chunk)
        experience_raw = exp_match.group(1) if exp_match else "Не указан"
        experience = exp_map.get(experience_raw, experience_raw)
        
        # 7. График работы 
        schedule_matches = re.findall(r'"@workSchedule"\s*:\s*"([^"]+)"', prev_chunk)
        schedule_raw = schedule_matches[-1] if schedule_matches else "Не указан"
        schedule = schedule_map.get(schedule_raw, schedule_raw)
        
        # 8. Формат занятости
        emp_match = re.search(r'"employmentForm"\s*:\s*"([^"]+)"', chunk)
        employment_raw = emp_match.group(1) if emp_match else "Не указан"
        employment = emp_map.get(employment_raw, employment_raw)

        vacancies.append({
            "id": vacancy_id,
            "url": vacancy_url,
            "title": name,
            "company": company,
            "salary": salary,
            "experience": experience,
            "schedule": schedule,
            "employment": employment
        })

    return vacancies

def to_db(df:pd.DataFrame,pastdate:date):
    try:
        # Подсоединение базы данных
        connection = psycopg2.connect (dbname=f'{DB_name}',
                                        user=f'{DB_User}',
                                    password =f'{DB_password}',
                                    host=f'{DB_host}',
                                    port=f'{DB_port}')
        connection.autocommit = True
        # Курсор 
        cur = connection.cursor()


        #Сохранено для подходящего описания архитекутуры таблицы
        cur.execute(f'''CREATE TABLE IF NOT EXISTS it (
                    id INT PRIMARY KEY,
                    url VARCHAR(150) NOT NULL,
                    title VARCHAR(100) NOT NULL,
                    company TEXT,
                    salary TEXT,
                    experience TEXT,
                    schedule TEXT,
                    employment TEXT,
                    adding_date DATE);
                    ''')
        # и для этой команды, чтобы не выкинуло ошибку
        cur.execute('''SELECT 1 FROM it LIMIT 1;''')
        vacancies = cur.fetchone()
        
        engine = create_engine (f'postgresql+psycopg2://{DB_User}:{DB_password}@{DB_host}:{DB_port}/{DB_name}',
                                pool_pre_ping=True, # Важные части для разбора
                                connect_args={"options": "-c statement_timeout=15000"},)
        if vacancies is None:
            df.to_sql(name='it',
                    con=engine,
                    if_exists='append', # чтоб не заменяло
                    index=False
                    )
        else:
            cur.execute(f'''DELETE FROM it WHERE adding_date < '{pastdate}' ''')
            query = 'SELECT * FROM it'
            exist_vacancies = pd.read_sql(query, con=engine)
        

            #ВАЖНО
            df = df[~df['id'].isin(exist_vacancies['id'])]
            df = df[df['employment'] != 'Полная занятость']
            df = df[df['schedule'] != 'Полный день']

            df.to_sql(name='it',
                    con=engine,
                    if_exists='append',
                    index=False)

        cur.close()
        connection.close()
        engine.dispose()
        return df
    except Exception as e:
        print(f"Ошибка: {e}")
        traceback.print_exc()
        return pd.DataFrame()

def main():
    url_hh = [f'https://spb.hh.ru/search/vacancy?ored_clusters=true&area=2&search_field=name&search_field=company_name&search_field=description&enable_snippets=false&hhtmSourceLabel=vacancy_search_list&text=python&accept_temporary=false&experience=noExperience&experience=between1And3&page={i}' for i in range (1,4)]

    # блокирует, если использовать обычный get
    # Добавляет полный набор заголовков

    # Создает TCP соединение, которое хранит куки и заголовки, 
    # позволяет добавить настройки
    
    session = requests.Session()

    # Политика повторных подключений
    retry =  Retry( 
        total =3, # 3 повтора
        connect = 3, # 3 повтора на ошибки соединения
        backoff_factor = 1.5, # экспоненциальная пауза между попытками
        status_forcelist=[429, 500, 502, 503, 504],  # на какие HTTP-коды повторять
    )
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7", 
        })
    

    adapter = HTTPAdapter(max_retries=retry)
    # Применяет политики подключения к обоим типам запросов
    session.mount('https://',adapter)
    session.mount('https://',adapter)
    
    for url_on in url_hh:
        try:  
            response = session.get(url_on, timeout=30)
            
            parsed_jobs = parse_hh_raw_page(response.text)

            df = pd.DataFrame(parsed_jobs)
            # print (df.head())

            today = date.today()

            df['adding_date'] = today
            df['id'] = pd.to_numeric(df['id'],errors='coerce').astype('Int64')


            delta = timedelta(days=5)
            past_date = today - delta

            df_jobs = to_db(df,past_date)
            if len(df_jobs) !=0:
                # print(df_jobs.iloc[:].to_string())
                
                telegram_bot(df_jobs)
            else: pass
        except requests.exceptions.ConnectionError as e:
            msg =  f"⚠️ Соединение оборвано\nURL: {url_on}\n{type(e).__name__}: {e}"
            print(msg)
            send_text(msg)
            continue
        except requests.exceptions.Timeout:
            msg = f"⏱ Таймаут запроса\nURL: {url_on}"
            print(msg)
            send_text(msg)
            continue
        except Exception as e:
            msg = f"❌ Ошибка в main()\nURL: {url_on}\n{type(e).__name__}: {e}"
            print(msg)
            traceback.print_exc()
            send_text(msg)
            continue

def run():
    try:
        while True:
            pause = randint(1,5)
            main()
            time.sleep(pause*ONE_HOUR)
    except KeyboardInterrupt:
        print('Программа остановлена')
run()