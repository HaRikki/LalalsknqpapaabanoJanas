# មគ្គុទ្ទេសក៍ Payment (ABA KHQR)

កន្លែងគ្រប់គ្រង៖ **Admin → ប៊ូតុង "Payment"** → ABA KHQR settings / Transactions។

## ដំឡើង (ធ្វើម្តងគត់)
1. ចូល khmer-system.com → ទំព័រ **Profile** → ចម្លង **Profile Key** (api_key)។ (Key នេះមិនមានក្នុងឯកសារដែលអ្នកផ្ញើមកទេ ត្រូវដាក់ដោយខ្លួនឯង។ វាត្រូវបានរក្សាទុកក្នុង database ហើយមិនដែលផ្ញើទៅ browser ទេ។)
2. Admin → Payment → ABA KHQR settings៖
   - **Profile Key** = key ខាងលើ
   - **Merchant ID** = `gSk5rq` (បំពេញស្រាប់)
   - **Base URL** = `https://khmer-system.com` (បំពេញស្រាប់)
   - **Credit username** (ស្រេចចិត្ត)៖ API ទាមទារ "username" ដើម្បី credit។ ដោយលំនាំដើមប្រព័ន្ធផ្ញើ username របស់អតិថិជនក្នុង panel។ បើ gateway បដិសេធ username ដែលមិនស្គាល់ សូមដាក់ username តែមួយរបស់អ្នកនៅទីនេះ។
3. ចុច **Test connection** (ហៅ API អានតែប៉ុណ្ណោះ មិនបង្កើត QR មិនកាត់លុយ) → ឃើញ "Connection OK"។
4. ធីក **Enable** → **Save**។ Badge ប្តូរទៅ **Active**។

## របៀបដែលអតិថិជនបង់
1. កុម្ម៉ង់សេវា (Order service) ជ្រើស plan និងរយៈពេល (1/6/12 ខែ) → ប្រព័ន្ធបង្កើត **វិក្កយបត្រ** ហើយបើកទំព័រ Billing។
2. ចុច **Pay with ABA KHQR** → បង្ហាញ QR card → ស្កេនជាមួយ ABA Mobile/ KHQR app។
3. Panel ពិនិត្យរាល់ 4 វិនាទី។ ពេលស្ថានភាព **PAID** ហើយ **ចំនួនទឹកប្រាក់ត្រូវនឹងវិក្កយបត្រ** → plan ដំណើរការ, កំណត់ថ្ងៃផុតកំណត់ (30 ថ្ងៃ × ចំនួនខែ), ជូនដំណឹង, ហើយហៅ `mark-credited` (មួយដងគត់)។
4. QR មានសុពលភាព ~3 នាទី។ ផុតពេល → ប៊ូតុង "Generate new QR"។

## ចំណុចសំខាន់សម្រាប់ Admin
- **ថ្លៃ QR**៖ QR នីមួយៗ $0.004 ពី wallet khmer-system។ បើ wallet ទាប QR បង្កើតមិនបាន (អតិថិជនឃើញសារទូទៅ "Payment is temporarily unavailable" ហើយ error ពិតត្រូវបាន print ក្នុង console server)។ ប្រព័ន្ធប្រើ QR ដដែលវិញប្រសិនបើនៅមានសុពលភាព ដើម្បីកុំឱ្យខាតលុយ។
- **Transactions tab**៖ បង្ហាញ order ដែលបង់តាម ABA ក្នុង panel និងបញ្ជី transaction ពី gateway ។ ប៊ូតុង **Check now** ពិនិត្យម្តងទៀតសម្រាប់ order ដែលអតិថិជនបិទ browser មុនពេលបញ្ចប់។
- **Sales → Orders**៖ Admin នៅតែអាច Confirm/Reject ដោយដៃ។
- **ការពារ**៖ បើចំនួនទឹកប្រាក់ដែលបានបង់ ≠ វិក្កយបត្រ → មិន activate ហើយកត់ត្រា `payment_amount_mismatch` ក្នុង Audit។ payment_id ត្រូវបានរក្សាទុកខាង server ប៉ុណ្ណោះ អតិថិជនមិនអាចបញ្ជូនវាមកខ្លួនឯងបានទេ។
- **ការចាក់សោរ**៖ ពេល Payment បើក សេវាដែលមានវិក្កយបត្រមិនទាន់បង់ មិនអាច Start បានទេ (Admin និងសេវាចាស់ៗមិនប៉ះពាល់)។
- បើបិទ Payment ប្រព័ន្ធត្រឡប់ទៅការបង្កើតសេវាដោយឥតគិតថ្លៃដូចមុន។

## កំហុសដែលអាចជួប
| Code | មានន័យ |
|---|---|
| INVALID_KEY | Profile Key ខុស |
| QR_GENERATION_FAILED | Wallet khmer-system ទាបពេក |
| INVALID_REQUEST | username មិនត្រឹមត្រូវ ឬចំនួនទឹកប្រាក់ក្រៅដែនកំណត់ merchant (សាកដាក់ Credit username) |
| RATE_LIMITED / DAILY_LIMIT_REACHED | លើសដែនកំណត់ (429) |
| GATEWAY_DOWN | gateway មិនដំណើរការបណ្តោះអាសន្ន |
