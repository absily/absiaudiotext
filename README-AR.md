# ABSI Audio Cloud — دليل الإعداد (نسخة تجريبية)

الهدف: تحويل مقالات [ABSI.CC](https://www.absi.cc) إلى MP3 عربي بصوت Piper Kareem من دون تشغيل الكمبيوتر.

**الحالة:** تم رفع الشفرة إلى GitHub، ولم يتم إثبات عملها على Render أو Cloudflare حتى الآن.

## البنية
1. Cloudflare Worker يجلب آخر 25 مقالًا من خلاصة Blogger العامة كل ساعتين.
2. يتجاوز المقالات التي سجلت سابقًا في R2، ويعالج مقالًا جديدًا واحدًا في كل تشغيل.
3. يرسل محتوى المقال إلى خادم Render عبر HTTPS وبمفتاح مشترك.
4. يقوم Python + Piper بإنتاج WAV ثم FFmpeg لإنتاج MP3 ويحفظه في R2.
5. يعرض مشغّل Blogger رابط الاستماع فقط عند وجود MP3.

## الخطوات المتبقية
1. في Cloudflare R2 أنشئ bucket باسم `absi-audio`. قد يلزم إعداد الفوترة حتى ضمن الحصة المجانية.
2. أنشئ R2 API Token محدودًا بالـ bucket. لا تشارك المفاتيح داخل الدردشة أو GitHub.
3. في Render: New → Blueprint، صل هذا المستودع، وأنشئ خدمة وفق `render.yaml`، وأدخل الأسرار: `WORKER_SHARED_SECRET` و`R2_ENDPOINT` و`R2_ACCESS_KEY_ID` و`R2_SECRET_ACCESS_KEY` و`R2_BUCKET`.
4. بعد ظهور `/health` والتأكد أن `voice_present` تساوي true، انشر Cloudflare Worker من `worker/index.js` مع R2 binding باسم `AUDIO_BUCKET`.
5. في Cloudflare أضف أسرار Worker: `RENDER_URL` و`WORKER_SHARED_SECRET` (بنفس القيمة المستخدمة في Render).
6. اختبر توليد مقال عربي كامل ووجود MP3 حقيقي في R2، ثم أضف `blogger/widget.html` بعد تغيير WORKER_URL إلى العنوان الفعلي.

لا تغيّر قالب ABSI قبل نجاح التوليد. يمنع رفع الأسرار إلى المستودع العام.

## قيود الإصدار الحالي
- المقالات التي يزيد نصها عن 18,000 حرف ترفض بدل قصها بصمت.
- لا يعاد التسجيل عند تعديل المقال.
- لا أكثر من مقال واحد جديد في تشغيل كل ساعتين.
- لا يمكن اعتبار Render المجاني استضافة مضمونة: الخدمة تنام وقد تنفد الموارد.
- عند تفعيل R2 انتبه لاحتمال الحاجة إلى وسيلة دفع والرسوم بعد تجاوز الحصة.

## الاختبارات
`python -m pytest -q tests/`
`node --check worker/index.js`

المراجع:
https://render.com/docs/free
https://developers.cloudflare.com/workers/configuration/cron-triggers/
https://developers.cloudflare.com/r2/
https://huggingface.co/rhasspy/piper-voices/tree/main/ar/ar_JO/kareem/medium
