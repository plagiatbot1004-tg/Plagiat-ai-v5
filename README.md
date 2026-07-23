# PlagiAI Telegram Bot Professional V5 - Quetext

PlagiAI PDF, DOCX va TXT hujjatlardan matn ajratadi, Quetext DeepSearch API
orqali ochiq internet va akademik veb manbalar bilan tekshiradi hamda yakuniy
professional PDF hisobot yaratadi. Ichki hujjatlar o‘xshashligi ishlatilmaydi.

## Asosiy imkoniyatlar

- PDF, DOCX va TXT fayllardan matn ajratish;
- Quetext DeepSearch orqali real plagiat tekshiruvi;
- internet originalligi, o‘xshashlik foizi va manba havolalari;
- inglizcha matnda Quetext AI Detector va gaplar kesimidagi ehtimollar;
- o‘zbekcha matnda ehtiyotkor, past ishonchli uslubiy-statistik indikator;
- mualliflikni tekshirish savollari;
- faqat yakunlangan plagiat skanidan keyin professional PDF;
- webhook o‘rniga polling - Railway domeni va webhook secret kerak emas;
- Railway qayta ishga tushsa, tugallanmagan vazifalarni bazadan davom ettirish;
- PostgreSQL, Railway va Docker bilan ishlash.

> AI indikatori mualliflikni isbotlamaydi. O‘zbekcha indikator ayniqsa ehtiyotkor
> talqin qilinishi kerak. Yakuniy akademik qarorni inson eksperti qabul qiladi.

## Railway Variables

| O‘zgaruvchi | Qiymat |
|---|---|
| `BOT_TOKEN` | BotFather bergan token |
| `DATABASE_URL` | Railway PostgreSQL `DATABASE_URL` reference |
| `ADMIN_IDS` | Raqamli Telegram ID |
| `MAX_FILE_MB` | `20` |
| `MAX_TEXT_CHARS` | `200000` |
| `QUETEXT_API_KEY` | Quetext `Account > API Keys` bo‘limidagi kalit |
| `QUETEXT_POLL_SECONDS` | Ixtiyoriy, standart `3` |
| `QUETEXT_TIMEOUT_SECONDS` | Ixtiyoriy, standart `240` |

`PORT`ni Railway avtomatik beradi. Oldingi `COPYLEAKS_*`, `PUBLIC_BASE_URL` va
`WEBHOOK_SECRET` qiymatlari V5 da ishlatilmaydi va o‘chirilishi mumkin.

## Quetext API kaliti

1. `https://www.quetext.com/` saytida hisob oching.
2. Account ichidagi `API Keys` bo‘limiga kiring.
3. Yangi API key yarating.
4. Kalitni Railway bot servisidagi `QUETEXT_API_KEY` variable’iga kiriting.
5. Deploy tugagach botga kamida 20 so‘zli hujjat yuboring.

Yangi API hisobiga $5, ya’ni 50 000 so‘zlik sinov krediti beriladi. API wallet
oddiy Quetext obunasidan alohida. Har bir plagiat POST so‘rovi 1 000 so‘z uchun
$0.10, AI POST so‘rovi ham 1 000 so‘z uchun $0.10 turadi. Inglizcha hujjatda
ikkalasi ishlatilsa, umumiy narx 1 000 hujjat so‘zi uchun taxminan $0.20 bo‘ladi.

## Tekshiruv oqimi

1. Bot hujjatdan matn ajratadi va Quetext’ga plagiat so‘rovini yuboradi.
2. Inglizcha matnda alohida AI so‘rovi ham yuboriladi.
3. Bot har 3 soniyada hisobot holatini tekshiradi.
4. Plagiat natijasi tayyor bo‘lgach manbalar va foizlar olinadi.
5. AI natijasi mavjud bo‘lsa gaplar kesimidagi ehtimollar qo‘shiladi.
6. Faqat shundan so‘ng Telegram xulosasi va bitta V5 PDF yuboriladi.
7. Plagiat skani xato bersa tekshirilmagan PDF yaratilmaydi.

## Til bo‘yicha izoh

Quetext rasmiy til ro‘yxatida o‘zbek va rus tillari ko‘rsatilmagan. Bot bunday
matnni plagiat endpointiga yuboradi, ammo natijaning tilga xos aniqligini
kafolatlamaydi. O‘zbekcha AI bo‘limida Quetext o‘rniga past ishonchli mahalliy
stilometrik indikator ishlatiladi. Tashqi Quetext AI tekshiruvi hozir inglizcha
matn uchun yoqilgan.

## Lokal ishga tushirish

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Brauzerda `http://localhost:8080/health` manzilida `provider: Quetext` chiqishi
kerak.
