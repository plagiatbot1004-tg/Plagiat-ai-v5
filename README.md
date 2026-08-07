# PlagiAI Telegram Bot Professional V6 - Multi-Source

PlagiAI PDF, DOCX va TXT hujjatlardan matn ajratadi, Quetext DeepSearch API
orqali ochiq internet va akademik veb manbalar bilan tekshiradi, shu bilan birga
oldin PlagAI bazasiga yuborilgan hujjatlar bilan ichki o‘xshashlikni hisoblaydi.
Internet va ichki baza dalillari ustma-ust tushsa bir marta hisoblanib, yakuniy
professional PDF hisobot va QR-verifikatsiyali sertifikat yaratiladi.

## Asosiy imkoniyatlar

- PDF, DOCX va TXT fayllardan matn ajratish;
- Quetext DeepSearch orqali real plagiat tekshiruvi;
- Quetext qaytargan barcha matchlar, URL, input offset va mos fragmentlar;
- PlagAI ichki hujjatlar bazasi bilan real so‘z-fragment solishtiruvi;
- O‘zbek lotin/kirill yozuvini bir xil taqqoslash alifbosiga normalizatsiya qilish;
- bir parcha bir nechta manbada topilsa uni yakuniy foizda bir marta hisoblash;
- Internet %, ichki baza %, umumiy o‘xshashlik % va umumiy originallik %;
- inglizcha matnda Quetext AI Detector va gaplar kesimidagi ehtimollar;
- o‘zbekcha matnda ehtiyotkor, past ishonchli uslubiy-statistik indikator;
- mualliflikni tekshirish savollari;
- faqat yakunlangan ko‘p manbali skandan keyin professional PDF va sertifikat;
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
| `QUETEXT_TIMEOUT_SECONDS` | Ixtiyoriy, standart `900` (15 daqiqa) |
| `PUBLIC_BASE_URL` | Ixtiyoriy, sertifikat QR/verifikatsiya domeni |
| `RAILWAY_PUBLIC_DOMAIN` | Railway avtomatik domeni; QR uchun fallback |

`PORT`ni Railway avtomatik beradi. Oldingi `COPYLEAKS_*` va `WEBHOOK_SECRET`
qiymatlari ishlatilmaydi. `PUBLIC_BASE_URL` esa V6 sertifikat QR-verifikatsiyasi
uchun foydali va mavjud bo‘lsa saqlanishi kerak.

## Quetext API kaliti

1. `https://www.quetext.com/` saytida hisob oching.
2. Account ichidagi `API Keys` bo‘limiga kiring.
3. Yangi API key yarating.
4. Kalitni Railway bot servisidagi `QUETEXT_API_KEY` variable’iga kiriting.
5. Deploy tugagach botga kamida 20 so‘zli hujjat yuboring.

Quetext amaldagi developer hujjatida yangi API hisobiga 5 000 bepul so‘z
ko‘rsatilgan. API wallet oddiy Quetext obunasidan alohida. Har bir plagiat POST
so‘rovi 1 000 so‘z uchun $0.10, AI POST so‘rovi ham 1 000 so‘z uchun $0.10
turadi. Inglizcha hujjatda ikkalasi ishlatilsa, umumiy narx 1 000 hujjat so‘zi
uchun taxminan $0.20 bo‘ladi.

## Tekshiruv oqimi

1. Bot hujjatdan matn ajratadi, UTF-8 xavfsizlaydi va bazaga saqlaydi.
2. Matn Quetext’ga internet/akademik plagiat so‘rovi sifatida yuboriladi.
3. Quetext ishlayotgan paytda hujjat V6 ichki taqqoslashga tayyor turadi.
4. Inglizcha matnda alohida AI so‘rovi ham yuboriladi.
5. Bot har 3 soniyada progress va yakuniy Quetext endpointlarini tekshiradi.
6. Quetext tugagach oldingi barcha PlagAI submissionlari bilan ichki skan bajariladi.
7. Kamida 8 so‘zli normalizatsiyalangan aniq fragmentlar manba va pozitsiya bilan qayd etiladi.
8. Internet va ichki fragmentlar ustma-ust joylarda de-dup qilinadi.
9. Umumiy o‘xshashlik/originallik saqlanadi va PDF + sertifikat yuboriladi.
10. Tashqi yoki ichki majburiy skan xato bersa tekshirilmagan yakuniy hujjat berilmaydi.

V6 progress yozuvi kechiksa ham tayyor natijani bevosita hisobot endpointidan
oladi. Standart kutish muddati 15 daqiqa; ko‘p hollarda natija ancha tez keladi.

## V6 ichki baza qanday ishlaydi

Ichki taqqoslash V6.1 da dalilga asoslangan aniq/normalizatsiyalangan matn
o‘xshashligini topadi. Registr, tinish belgisi va O‘zbek lotin/kirill yozuvidagi
farqlar normalizatsiya qilinadi. Har bir topilgan parcha joriy hujjatdagi
pozitsiyasi bilan saqlanadi. Bir parcha bir nechta eski hujjatda uchrasa yakuniy
foizga faqat bir marta kiradi.

Boshqa foydalanuvchining shaxsiy ma’lumoti hisobotga chiqarilmaydi; manba
`PlagAI ichki hujjat #ID` ko‘rinishida anonimlanadi. Foydalanuvchining o‘z oldingi
hujjati bo‘lsa uning fayl nomi ko‘rsatilishi mumkin.

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
