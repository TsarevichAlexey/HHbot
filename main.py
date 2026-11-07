import requests
import html
import re
import psycopg2
import pandas as pd
from sqlalchemy import create_engine

from config import *

def parse_hh_raw_page(raw_html):
    # 1. Раскодируем HTML-сущности (превращаем &#34; в обычные кавычки ")
    clean_text = html.unescape(raw_html)

    # 2. Разбиваем весь огромный текст на куски. 
    # Каждая вакансия привязана к своему "vacancyId", поэтому режем по нему.
    chunks = clean_text.split('"vacancyId":')

    vacancies = []

    # Словари для перевода значений на русский язык (как на самом сайте)
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

    # Начинаем с 1, так как chunks[0] — это техническая информация ДО первой вакансии
    for i in range(1, len(chunks)):
        chunk = chunks[i]       # Кусок данных ПОСЛЕ vacancyId
        prev_chunk = chunks[i-1] # Кусок данных ДО vacancyId (там прячется график работы)
        
        # --- ИЗВЛЕКАЕМ ДАННЫЕ ---
        
        # 1. ID вакансии (идет в самом начале текущего куска)
        v_id_match = re.match(r'^(\d+)', chunk)
        vacancy_id = v_id_match.group(1) if v_id_match else "Неизвестно"
        
        # 2. Название вакансии
        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', chunk)
        name = name_match.group(1) if name_match else "Не указано"
        
        # 3. Компания (ищем "name" внутри блока "company", ограничив поиск 300 символами, чтобы не захватить лишнего)
        company_match = re.search(r'"company"\s*:\s*\{.{0,300}?"name"\s*:\s*"([^"]+)"', chunk)
        company = company_match.group(1) if company_match else "Не указано"
        
        # 4. Зарплата
        salary_match = re.search(r'"compensation"\s*:\s*(\{.*?\})', chunk)
        salary = "Не указана"
        if salary_match:
            comp_data = salary_match.group(1)
            # Если нет пометки "noCompensation" (без компенсации)
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

        # 5. Требуемый опыт (workExperience)
        exp_match = re.search(r'"workExperience"\s*:\s*"([^"]+)"', chunk)
        experience_raw = exp_match.group(1) if exp_match else "Не указан"
        experience = exp_map.get(experience_raw, experience_raw)
        
        # 6. График работы (@workSchedule). 
        # В вашей структуре он идет ПЕРЕД vacancyId, поэтому мы берем его с конца ПРЕДЫДУЩЕГО куска
        schedule_matches = re.findall(r'"@workSchedule"\s*:\s*"([^"]+)"', prev_chunk)
        schedule_raw = schedule_matches[-1] if schedule_matches else "Не указан"
        schedule = schedule_map.get(schedule_raw, schedule_raw)
        
        # 7. Формат занятости (employment / employmentForm)
        emp_match = re.search(r'"employmentForm"\s*:\s*"([^"]+)"', chunk)
        employment_raw = emp_match.group(1) if emp_match else "Не указан"
        employment = emp_map.get(employment_raw, employment_raw)

        # Добавляем собранную информацию в наш список
        vacancies.append({
            "id": vacancy_id,
            "title": name,
            "company": company,
            "salary": salary,
            "experience": experience,
            "schedule": schedule,
            "employment": employment
        })

    return vacancies

def to_db(vacancies:list,df:pd.DataFrame):
    # Подсоединение базы данных
    connection = psycopg2.connect (dbname=f'{DB_name}',
                                    user=f'{DB_User}',
                                   password =f'{DB_password}',
                                   host=f'{DB_host}',
                                   port=f'{DB_port}')
    connection.autocommit = True
    # Курсор 
    cur = connection.cursor()


    cur.execute(f'''CREATE TABLE IF NOT EXISTS it (
                id INT PRIMARY KEY,
                title VARCHAR(50) NOT NULL,
                company TEXT,
                salary TEXT,
                experience TEXT,
                schedule TEXT,
                employment TEXT);
                ''')
    cur.execute('''SELECT title FROM it LIMIT 1;''')
    print(234)
    vacancies = cur.fetchone()
    print(1)
    engine = create_engine (f'postgresql+psycopg2://{DB_User}:{DB_password}@{DB_host}:{DB_port}/{DB_name}',
                            pool_pre_ping=True, # Важные части для разбора
                            connect_args={"options": "-c statement_timeout=15000"},)
    if vacancies is None:
        df.to_sql(name='it',
                  con=engine,
                  if_exists='replace',
                  index=False
                  )

    cur.execute('SELECT title FROM it')
    vacancies = cur.fetchall() #Список из кортежей из 1 слова

    #ВАЖНО
    """кортежи → список строк"""
    titles = [row[0] for row in vacancies]
    df = df[~df['company'].isin(titles)]

    df.to_sql(name='it',
              con=engine,
              if_exists='append',
              index=False)

    cur.close()
    connection.close()
    engine.dispose()
    return df


url_hh = [f'https://spb.hh.ru/search/vacancy?text=python&ored_clusters=true&area=2&page={i}' for i in range (1,4)]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
for url_on in url_hh:
    response = requests.get(url_on, headers=headers)

    parsed_jobs = parse_hh_raw_page(response.text)

    df = pd.DataFrame(parsed_jobs)
    print (df.columns)

    df = df[df['employment'] != "Полная занятость"]


    df_jobs = to_db(parsed_jobs,df)
    print(df.iloc[0].to_string())
    # for job in parsed_jobs:
    #     print(f"{job['title']} (ID: {job['id']})")
    #     print(f"Компания: {job['company']}")
    #     print(f"Зарплата: {job['salary']}")
    #     print(f"Опыт: {job['experience']}")
    #     print(f"График: {job['schedule']}, {job['employment']}")
    #     print("-" * 50)