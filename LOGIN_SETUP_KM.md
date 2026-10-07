# មគ្គុទ្ទេសក៍ Login ជាមួយ Google និង Telegram

កន្លែងគ្រប់គ្រង៖ **Admin panel → tab "Login"** (ចូលជា admin រួចចុច Admin → Login)។
មិនបាច់ restart ទេ — Save រួចប៊ូតុងលេចឡើងនៅទំព័រ Login/Register ភ្លាមៗ។

## ជំហានទី ០ — Site URL
ក្នុង tab Login បំពេញ **Site URL** ជា https address ពិតរបស់ panel (ឧ. `https://panel.yourdomain.com`)។
- ត្រូវតែជា **https** និងមិនមាន `/` ឬ path ខាងក្រោយ។
- ប្រសិនបើទុកទទេ ប្រព័ន្ធទាយពី domain ដែលអ្នកកំពុងប្រើ (ដំណើរការជាមួយ Cloudflare Tunnel)។ ប៉ុន្តែគួរបំពេញដើម្បីឱ្យច្បាស់។
- ប្រអប់ "Allow new users to register…" = អនុញ្ញាតឱ្យអ្នកថ្មីបង្កើតគណនីតាម Google/Telegram។ បិទវាបើចង់ឱ្យតែអ្នកមានគណនីស្រាប់ប៉ុណ្ណោះចូលបាន។

## A. Google
1. ចូល https://console.cloud.google.com → បង្កើត Project (ឬជ្រើសមួយដែលមាន)។
2. **APIs & Services → OAuth consent screen** → ជ្រើស External → បំពេញ App name, email → Save។ (ចាំបាច់ត្រូវ Publish app ទើបអ្នកផ្សេងចូលបាន បើមិនដូច្នោះទេ មានតែ Test users ប៉ុណ្ណោះ)
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → Application type = **Web application**។
4. ត្រង់ **Authorized redirect URIs** → ចុច Add → paste តម្លៃដែលបង្ហាញក្នុង Admin → Login (ក្រោមចំណងជើង Google) ឧ. `https://panel.yourdomain.com/auth/google/callback` ។ ត្រូវដូចគ្នាទាំងអស់ (ទាំង https និងគ្មាន `/` ខាងចុង)។
5. Create → ចម្លង **Client ID** និង **Client secret**។
6. ត្រឡប់មក Admin → Login៖ ដាក់ Client ID, Client Secret, ធីក **Enable Google login** → **Save**។
7. Badge "Google" ត្រូវប្តូរទៅ **Active** ។

## B. Telegram
1. ក្នុង Telegram ជជែកជាមួយ **@BotFather** → `/newbot` → ដាក់ឈ្មោះ និង username (បញ្ចប់ដោយ `bot`)។ វានឹងផ្តល់ **Bot token**។ (ឬប្រើ bot ដែលមានស្រាប់៖ `/mybots`)
2. ផ្ញើ `/setdomain` → ជ្រើស bot → ដាក់ domain ដែលបង្ហាញក្នុង Admin → Login (ក្រោម Telegram) ឧ. `panel.yourdomain.com` (គ្មាន https://)។ **ជំហាននេះចាំបាច់** បើមិនដូច្នោះប៊ូតុងមិនដំណើរការ។
3. Admin → Login៖ ដាក់ Bot token → ចុច **Verify token & fill username** (វាបំពេញ username ឱ្យអូតូ) → ធីក **Enable Telegram login** → **Save**។
4. ប៊ូតុង "Continue with Telegram" បើក popup របស់ Telegram (ត្រូវអនុញ្ញាតឱ្យ browser បើក popup)។ ចុច Accept ក្នុង popup រួចចូលគណនីភ្លាម។
5. ចំណាំ៖ Telegram មិនដំណើរការលើ `localhost` ឬ IP — ត្រូវមាន domain https ពិត (Cloudflare Tunnel ប្រើបាន)។

## អ្វីដែល Admin ត្រូវដឹងបន្ថែម
- **Recent logins** (ក្នុង tab Login) បង្ហាញ 50 ចូលចុងក្រោយ៖ ពេល, user, វិធី (password/google/telegram), ជោគជ័យ ឬបរាជ័យ, IP។
- **Users tab** មានជួរ "Sign-in" បង្ហាញវិធី (G = Google ភ្ជាប់, TG = Telegram ភ្ជាប់)។ អ្នកប្រើអាច Suspend បានដូចធម្មតា — user ដែលត្រូវ suspend ចូលតាម Google/Telegram មិនបានទេ។
- **Audit tab** កត់ត្រា៖ `login_google`, `login_telegram`, `register_google`, `register_telegram`, `link_*`, `unlink_*`, `admin_auth_settings`។
- Google៖ បើអ៊ីមែលរបស់ Google ត្រូវនឹងគណនីដែលមានស្រាប់ (ធម្មតា) ប្រព័ន្ធភ្ជាប់ឱ្យអូតូ។ **គណនី Admin មិនត្រូវបានភ្ជាប់អូតូទេ** (សុវត្ថិភាព) — admin ត្រូវ login ដោយ password រួចចូល Settings → Security → Connected accounts → Link Google/Telegram។
- អ្នកដែលចុះឈ្មោះតាម Telegram ទទួលបានអ៊ីមែលក្លែងក្លាយ `tg<ID>@telegram.local` (Telegram មិនផ្តល់អ៊ីមែល)។
- អ្នកដែលចុះឈ្មោះតាម Google/Telegram អាចកំណត់ password ក្នុង Settings → Security ដោយមិនបាច់ដឹង password ចាស់។
- ប៊ូតុង "Remove … keys" លុប key ចេញពី database។ ការទុកទទេនៅ Client Secret/Bot token = រក្សាតម្លៃដែលបានរក្សាទុកស្រាប់។
- (ជម្រើស) ក៏អាចដាក់ key ក្នុង `.env` (`GOOGLE_CLIENT_ID` …) ជា fallback ប៉ុន្តែតម្លៃក្នុង Admin ជាអាទិភាព។

## បញ្ហាដែលអាចជួបប្រទះ
| អាការ | មូលហេតុ / ដំណោះស្រាយ |
|---|---|
| Google: `redirect_uri_mismatch` | Redirect URI ក្នុង Google Cloud មិនដូច URI ក្នុង Admin បេះបិទ (https, ចុង path) |
| Google: "Google rejected the login" | Client ID/Secret ខុស ឬ Site URL មិនត្រូវ |
| Google: "Access blocked" | OAuth consent screen នៅ Testing — បន្ថែម Test users ឬ Publish app |
| Telegram: ប៊ូតុងមិនលេច / "Bot domain invalid" | មិនទាន់ `/setdomain` ឬ username bot ខុស |
| Telegram: "invalid or expired" | Bot token ក្នុង Admin មិនត្រូវនឹង bot ដែលបង្ហាញ, ឬម៉ោង server ខុស |
| ប៊ូតុងមិនបង្ហាញ | ភ្លេចធីក Enable ឬបំពេញមិនគ្រប់ (badge បង្ហាញ "Incomplete") |
