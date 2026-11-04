# بوت وظايف NHS على تليجرام

البوت ده بيدور كل ٥ دقايق في مواقع الوظايف الرسمية في بريطانيا كلها:
- **إنجلترا وويلز:** NHS Jobs (jobs.nhs.uk)
- **اسكتلندا:** NHS Scotland (apply.jobs.scot.nhs.uk)
- **أيرلندا الشمالية:** HSC Jobs (jobs.hscni.net)

و وأول ما تنزل وظيفة جديدة مناسبة ليك بيبعتلك رسالة على تليجرام.

**الوظايف اللي بيدور عليها:**
- **الدرجة:** FY2، ST1، ST2، IMT1/2، SHO، Junior Clinical Fellow، Trust grade/Trust doctor
- **التخصص:** General Medicine، Geriatrics/COTE، Acute Medicine، Gastroenterology/Hepatology، Nephrology/Renal، Stroke، Neurology، Haematology، Endocrinology/Diabetes، Respiratory

**بيستبعد:**
- أي وظيفة الـMRCP فيها **Essential**. لو الـMRCP مكتوبة Desirable أو مش مذكورة، الوظيفة بتوصلك.
- أي وظيفة خبرة الـNHS أو الـHSC أو الخبرة في بريطانيا فيها **Essential**.
- وظايف "Open to HSC employees only" (للموظفين الحاليين بس).
- أي وظيفة مكتوب فيها إن الـvisa sponsorship مش متاحة. تقدر تلغي الشرط ده من الإعدادات.
- الوظايف الأعلى (Senior fellow، Registrar، Consultant، Specialty doctor) والتخصصات التانية.

---

## التشغيل (حوالي ١٥ دقيقة، مرة واحدة بس)

### ١) اعمل بوت تليجرام
1. افتح تليجرام وابعت لـ **@BotFather** الأمر `/newbot`، واختار اسم للبوت.
2. هيبعتلك **Token** شكله كده `123456:ABC-xyz...`. احفظه.
3. افتح البوت الجديد واضغط **Start** وابعتله أي رسالة.
4. افتح الرابط ده في المتصفح، بعد ما تحط الـToken بتاعك مكان TOKEN:
   `https://api.telegram.org/botTOKEN/getUpdates`
   هتلاقي `"chat":{"id":123456789` ... الرقم ده هو **Chat ID**.

### ٢) ارفع الملفات على GitHub
1. اعمل حساب على github.com لو مش معاك.
2. اعمل **New repository**، وخليه **Public**. الـrepo لازم يكون Public علشان دقايق التشغيل تبقى مجانية من غير حد. الـToken مش هيظهر لحد، لأنه بيتحفظ في Secrets.
3. اضغط **Add file → Upload files** وارفع كل الملفات اللي جوه الفولدر. لازم فولدر `.github/workflows` يترفع زي ما هو.
   (لو المتصفح ما رفعش الفولدر المخفي: اضغط **Add file → Create new file**، واكتب في الاسم `.github/workflows/job-bot.yml`، والصق محتوى الملف.)

### ٣) حط الـSecrets
في الـrepo: **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN` = الـToken
- `TELEGRAM_CHAT_ID` = الـChat ID

### ٤) اسمحله يحفظ الوظايف اللي شافها
**Settings → Actions → General → Workflow permissions** ← اختار **Read and write permissions** ← Save

### ٥) جرّبه
**Actions → NHS job alerts → Run workflow**
في خلال دقيقة أو اتنين هيوصلك على تليجرام: الوظايف المفتوحة دلوقتي والمطابقة لشروطك، ورسالة "البوت اشتغل". بعد كده هيشتغل لوحده كل ٥ دقايق.

---

## ملاحظات
- **السرعة:** GitHub ساعات بيأخر التشغيل المجدول كام دقيقة. لو عايز أسرع، شغّله على الكمبيوتر بتاعك:
  ```
  pip install -r requirements.txt
  set TELEGRAM_BOT_TOKEN=...   (على ماك أو لينكس: export بدل set)
  set TELEGRAM_CHAT_ID=...
  python nhs_job_bot.py --loop 180
  ```
  كده هيدور كل ٣ دقايق طول ما الجهاز شغال.
- **لو الإعلان مش فيه Person specification** (يعني الشروط في ملف PDF مرفق)، الرسالة هتوصلك وعليها ⚠️. راجع الملف قبل ما تقدم.
- **فلتر الشروط بيقرا النص بشكل آلي** وممكن يغلط في إعلانات مكتوبة بشكل غريب. ابص على الـPerson specification بنفسك قبل ما تقدم.
- **لو وصلتك رسالة "البوت مش لاقي أي نتايج"**، يبقى غالبًا شكل موقع NHS Jobs اتغير والكود محتاج تحديث بسيط.
- **لتعديل الكلمات أو الفلاتر:** افتح `nhs_job_bot.py` وعدّل القوايم اللي في أول الملف تحت `SETTINGS`.
- **GitHub بيوقف الـworkflows المجدولة** لو الـrepo فضل ٦٠ يوم من غير أي نشاط. البوت بيعمل commit لوحده كل ما يلاقي وظايف جديدة، فالمفروض يفضل شغال. لو وقف، ادخل على Actions وفعّله تاني.
- **اسكتلندا:** معظم الإعلانات هناك بتحط الشروط في Job pack منفصل، فالرسايل غالبًا هتوصلك وعليها ⚠️. افتح الـJob pack واتأكد بنفسك من شرط الـMRCP وخبرة الـNHS.
- **أيرلندا الشمالية:** إعلانات كتير بتحولك على موقع HealthDaq. البوت بيفتح الصفحة دي كمان ويقرا الشروط منها.
- **لو موقع واحد بس فيهم اتغير شكله**، هيوصلك تنبيه باسمه، وباقي المواقع هتفضل شغالة عادي. وتقدر تقفل أي موقع من `SOURCES` في أول الملف.
