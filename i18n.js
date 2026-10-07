/* Anajak Host — EN / ខ្មែរ switcher (translates static text by exact match) */
(function () {
  const KM = {
    // file manager (trash / selection)
    "Delete Files":"លុបឯកសារ","Move to trash":"ផ្លាស់ទៅធុងសំរាម","Permanently delete":"លុបជាអចិន្ត្រៃយ៍","Archive":"បង្ហាប់","Trash":"ធុងសំរាម","Restore":"ស្ដារឡើងវិញ","Delete forever":"លុបចោលរហូត",
    "Empty trash":"សម្អាតធុងសំរាម","selected":"បានជ្រើស","This directory seems to be empty.":"ថតនេះហាក់ដូចជាទទេ។","The trash is empty.":"ធុងសំរាមទទេ។","Moved to trash":"បានផ្លាស់ទៅធុងសំរាម","No files match your search.":"រកមិនឃើញឯកសារ។",
    "Are you sure you want to delete":"តើអ្នកប្រាកដថាចង់លុប","Permanently deleted files cannot be recovered. Files moved to the trash can be restored from the Trash.":"ឯកសារដែលលុបជាអចិន្ត្រៃយ៍មិនអាចស្ដារបានទេ។ ឯកសារក្នុងធុងសំរាមអាចស្ដារឡើងវិញបាន។","and":"និង","others":"ផ្សេងទៀត",
    // nav
    "Main":"ម៉ឺនុយ","Account":"គណនី","Admin":"អ្នកគ្រប់គ្រង","My services":"សេវាកម្មរបស់ខ្ញុំ","Order new service":"កុម្ម៉ង់សេវាថ្មី",
    "Billing":"ការទូទាត់","Support":"ជំនួយ","Notifications":"ការជូនដំណឹង","Profile & security":"ប្រវត្តិរូប និងសុវត្ថិភាព","Admin panel":"ផ្ទាំងអ្នកគ្រប់គ្រង",
    "Logout":"ចាកចេញ","Login":"ចូលគណនី","Register":"ចុះឈ្មោះ","Dashboard":"ផ្ទាំងគ្រប់គ្រង","Cloud hosting":"ម៉ាស៊ីនបម្រើពពក",
    // home
    "Deploy your project in seconds":"ដាក់ដំណើរការគម្រោងរបស់អ្នកក្នុងរយៈពេលប៉ុន្មានវិនាទី",
    "Bots, websites, APIs and custom apps — one control panel.":"Bot, គេហទំព័រ, API និងកម្មវិធីផ្សេងៗ — ក្នុងផ្ទាំងគ្រប់គ្រងតែមួយ។",
    "Get Started":"ចាប់ផ្តើម","My Services":"សេវាកម្មរបស់ខ្ញុំ","What you can host":"អ្វីដែលអ្នកអាចបង្ហោះបាន","Everything in one place":"អ្វីៗទាំងអស់នៅកន្លែងតែមួយ",
    "Cloud Hosting":"ម៉ាស៊ីនបម្រើពពក","Bot Hosting":"បង្ហោះ Bot","Website":"គេហទំព័រ","API / Backend":"API / Backend","Game Server":"ម៉ាស៊ីនបម្រើហ្គេម","Live Console":"កុងសូលផ្ទាល់",
    "Apps, APIs and custom backends.":"កម្មវិធី, API និង backend តាមតម្រូវការ។","Telegram and Discord bots with live logs.":"Bot Telegram និង Discord ជាមួយ log ផ្ទាល់។",
    "Deploy websites and web apps.":"បង្ហោះគេហទំព័រ និងកម្មវិធីវេប។","Python, Node.js, Java, Bun.":"Python, Node.js, Java, Bun។",
    "Game templates with resource limits.":"ពុម្ពហ្គេមដែលមានកំណត់ធនធាន។","Logs, files and env vars in the browser.":"Log, ឯកសារ និង env នៅក្នុង browser។",
    "Get started →":"ចាប់ផ្តើម →","Select →":"ជ្រើសរើស →","How it works":"របៀបដំណើរការ","Start in 3 steps":"ចាប់ផ្តើមក្នុង ៣ ជំហាន",
    "Create account":"បង្កើតគណនី","Register with your email in a few seconds.":"ចុះឈ្មោះដោយអ៊ីមែលរបស់អ្នកក្នុងពេលប៉ុន្មានវិនាទី។",
    "Choose a plan":"ជ្រើសរើសគម្រោង","Pick hosting type, RAM, CPU and storage.":"ជ្រើសប្រភេទ, RAM, CPU និងទំហំផ្ទុក។",
    "Deploy & manage":"បង្ហោះ និងគ្រប់គ្រង","Upload files, set env vars, then press Start.":"ផ្ទុកឯកសារឡើង កំណត់ env រួចចុច Start។",
    "Order your first service":"កុម្ម៉ង់សេវាដំបូងរបស់អ្នក",
    // auth
    "Sign in to your account":"ចូលទៅកាន់គណនីរបស់អ្នក","Email":"អ៊ីមែល","Password":"ពាក្យសម្ងាត់","Enter your email":"បញ្ចូលអ៊ីមែលរបស់អ្នក","Enter your password":"បញ្ចូលពាក្យសម្ងាត់",
    "No account?":"មិនទាន់មានគណនី?","Have an account?":"មានគណនីរួចហើយ?","Start hosting in a few steps":"ចាប់ផ្តើមបង្ហោះក្នុងប៉ុន្មានជំហានប៉ុណ្ណោះ",
    "Full name":"ឈ្មោះពេញ","Your name":"ឈ្មោះរបស់អ្នក","Username":"ឈ្មោះអ្នកប្រើ","or continue with":"ឬបន្តជាមួយ","Continue with Google":"បន្តជាមួយ Google","Login":"ចូលគណនី","Min 6 characters":"យ៉ាងតិច ៦ តួអក្សរ",
    // dashboard
    "Manage your hosting services":"គ្រប់គ្រងសេវាបង្ហោះរបស់អ្នក","+ Order New Service":"+ កុម្ម៉ង់សេវាថ្មី","Order New Service":"កុម្ម៉ង់សេវាថ្មី",
    "Total services":"សេវាសរុប","Active":"កំពុងដំណើរការ","Unread alerts":"ការជូនដំណឹងមិនទាន់អាន","No services yet":"មិនទាន់មានសេវាកម្មទេ",
    "Order your first hosting to continue.":"កុម្ម៉ង់ hosting ដំបូងរបស់អ្នកដើម្បីបន្ត។","Price":"តម្លៃ","Expires at":"ផុតកំណត់នៅ","Manage service":"គ្រប់គ្រងសេវា",
    // order
    "Hosting type":"ប្រភេទ hosting","Plan":"គម្រោង","Configure":"កំណត់រចនាសម្ព័ន្ធ","Choose your hosting type":"ជ្រើសរើសប្រភេទ hosting",
    "Bot, website, API, game or cloud hosting.":"Bot, គេហទំព័រ, API, ហ្គេម ឬ cloud hosting។","Telegram Bot":"Bot Telegram","Discord Bot":"Bot Discord",
    "Host Telegram bots with logs and env vars.":"បង្ហោះ Bot Telegram ជាមួយ log និង env។","Run Discord bots on isolated processes.":"ដំណើរការ Bot Discord ដាច់ដោយឡែក។",
    "Python, Node.js and custom backends.":"Python, Node.js និង backend ផ្សេងៗ។","Apps, APIs, bots, and any custom stack.":"កម្មវិធី, API, Bot និងអ្វីៗផ្សេងទៀត។",
    "Select your plan":"ជ្រើសរើសគម្រោងរបស់អ្នក","Compare price, RAM, CPU and storage.":"ប្រៀបធៀបតម្លៃ, RAM, CPU និងទំហំផ្ទុក។","← All hosting types":"← ប្រភេទ hosting ទាំងអស់",
    "Your order":"ការកុម្ម៉ង់របស់អ្នក","Select a plan to continue":"ជ្រើសគម្រោងដើម្បីបន្ត","Total":"សរុប","Continue":"បន្ត","No plans. Ask admin to add plans.":"មិនមានគម្រោងទេ។ សូមប្រាប់អ្នកគ្រប់គ្រងឱ្យបន្ថែម។",
    "Configure your order":"កំណត់ការកុម្ម៉ង់របស់អ្នក","Choose billing cycle and server options.":"ជ្រើសរយៈពេលទូទាត់ និងជម្រើសម៉ាស៊ីន។","← Back to plans":"← ត្រឡប់ទៅគម្រោង",
    "Billing cycle":"រយៈពេលទូទាត់","Monthly":"ប្រចាំខែ","Semi-Annually":"ប្រចាំ ៦ ខែ","Annually":"ប្រចាំឆ្នាំ","per month":"ក្នុងមួយខែ","per 6 months":"ក្នុង ៦ ខែ","per year":"ក្នុងមួយឆ្នាំ",
    "Server":"ម៉ាស៊ីន","Server Name":"ឈ្មោះម៉ាស៊ីន","Start command (optional)":"ពាក្យបញ្ជាចាប់ផ្តើម (ស្រេចចិត្ត)","Runtime":"Runtime","Place order":"បញ្ជាក់ការកុម្ម៉ង់",
    // project
    "← My services":"← សេវាកម្មរបស់ខ្ញុំ","Start":"ចាប់ផ្តើម","Restart":"ចាប់ផ្តើមឡើងវិញ","Stop":"បញ្ឈប់","CPU Usage":"ការប្រើ CPU","Memory":"អង្គចងចាំ","Server Info":"ព័ត៌មានម៉ាស៊ីន",
    "Status":"ស្ថានភាព","Type":"ប្រភេទ","Port":"ច្រក","Expires":"ផុតកំណត់","Console":"កុងសូល","Files":"ឯកសារ","Env":"Env","Settings":"ការកំណត់","Refresh":"ផ្ទុកឡើងវិញ",
    "No logs yet.":"មិនទាន់មាន log ទេ។","No logs":"គ្មាន log","Upload":"ផ្ទុកឡើង","Add":"បន្ថែម","Delete":"លុប","No variables":"មិនមានអថេរទេ","Empty":"ទទេ","Start command":"ពាក្យបញ្ជាចាប់ផ្តើម",
    "Domain":"ដែន","Save":"រក្សាទុក","Delete service":"លុបសេវា","Saved":"បានរក្សាទុក",
    // billing
    "Plans, orders and payments":"គម្រោង, ការកុម្ម៉ង់ និងការទូទាត់","+ Order service":"+ កុម្ម៉ង់សេវា","Available plans":"គម្រោងដែលមាន","Select plan":"ជ្រើសគម្រោងនេះ","No plans available":"មិនមានគម្រោងទេ",
    "Your orders":"ការកុម្ម៉ង់របស់អ្នក","Amount":"ចំនួនទឹកប្រាក់","Date":"កាលបរិច្ឆេទ","No orders yet":"មិនទាន់មានការកុម្ម៉ង់",
    // settings/support/notifications
    "Account settings":"ការកំណត់គណនី","Profile and security":"ប្រវត្តិរូប និងសុវត្ថិភាព","Profile":"ប្រវត្តិរូប","Save profile":"រក្សាទុកប្រវត្តិរូប","Current password":"ពាក្យសម្ងាត់បច្ចុប្បន្ន",
    "New password":"ពាក្យសម្ងាត់ថ្មី","Change password":"ប្តូរពាក្យសម្ងាត់","Open a ticket if you need help":"បើកសំបុត្រប្រសិនបើអ្នកត្រូវការជំនួយ","New ticket":"សំបុត្រថ្មី","Subject":"ប្រធានបទ",
    "Message":"សារ","Short subject":"ប្រធានបទខ្លី","Describe your issue":"ពិពណ៌នាបញ្ហារបស់អ្នក","Submit ticket":"ផ្ញើសំបុត្រ","Your tickets":"សំបុត្ររបស់អ្នក","No tickets yet":"មិនទាន់មានសំបុត្រ",
    "← All tickets":"← សំបុត្រទាំងអស់","Reply":"ឆ្លើយតប","Write your reply...":"សរសេរចម្លើយរបស់អ្នក...","Send":"ផ្ញើ","Close ticket":"បិទសំបុត្រ","Staff":"បុគ្គលិក","You":"អ្នក",
    "Updates about your services and account":"ព័ត៌មានថ្មីអំពីសេវា និងគណនីរបស់អ្នក","Mark all read":"សម្គាល់ថាអានអស់","No notifications":"មិនមានការជូនដំណឹង",
    // admin
    "Users, services, orders and system":"អ្នកប្រើ, សេវា, ការកុម្ម៉ង់ និងប្រព័ន្ធ","Users":"អ្នកប្រើ","Projects":"គម្រោង","Running":"កំពុងដំណើរការ","Pending Orders":"ការកុម្ម៉ង់រង់ចាំ",
    "Orders":"ការកុម្ម៉ង់","Plans":"គម្រោង","Games":"ហ្គេម","System":"ប្រព័ន្ធ","Broadcast":"ផ្សព្វផ្សាយ","Audit":"កំណត់ហេតុ","Actions":"សកម្មភាព","Role":"តួនាទី","Name":"ឈ្មោះ","User":"អ្នកប្រើ",
    "Method":"វិធីសាស្ត្រ","Suspend":"ផ្អាក","Activate":"បើកដំណើរការ","Confirm":"បញ្ជាក់","Reject":"បដិសេធ","Toggle":"បិទ/បើក","Add Plan":"បន្ថែមគម្រោង","Create Plan":"បង្កើតគម្រោង","Create":"បង្កើត",
    "Add Game Template":"បន្ថែមពុម្ពហ្គេម","No tickets":"គ្មានសំបុត្រ","Title":"ចំណងជើង","Body":"ខ្លឹមសារ","Send to all users":"ផ្ញើទៅអ្នកប្រើទាំងអស់","Time":"ពេលវេលា","Detail":"ព័ត៌មានលម្អិត","Action":"សកម្មភាព",
    "© Anajak Host · Cloud hosting for bots, websites, APIs & games":"© Anajak Host · Cloud hosting សម្រាប់ Bot, គេហទំព័រ, API និងហ្គេម"
  };
  
  // ---- Server panel (list + detail), dialogs and toasts ----
  Object.assign(KM, {
    "Servers":"ម៉ាស៊ីនបម្រើ","Manage your hosting services":"គ្រប់គ្រងសេវាកម្មបង្ហោះរបស់អ្នក","+ Order New Service":"+ កុម្ម៉ង់សេវាថ្មី",
    "No services yet":"មិនទាន់មានសេវាកម្មទេ","Order your first hosting to continue.":"កុម្ម៉ង់សេវាបង្ហោះដំបូងរបស់អ្នកដើម្បីបន្ត។","Order New Service":"កុម្ម៉ង់សេវាថ្មី",
    "Hostname:":"ឈ្មោះម៉ាស៊ីន៖","Server IP:":"IP ម៉ាស៊ីន៖","CPU:":"CPU៖","RAM:":"RAM៖","Disk:":"ថាស៖","Manage server":"គ្រប់គ្រងម៉ាស៊ីន",
    "Running":"កំពុងដំណើរការ","Offline":"ឈប់ដំណើរការ","Search servers…":"ស្វែងរកម៉ាស៊ីន…","All":"ទាំងអស់","Start":"ចាប់ផ្តើម","Stop":"បញ្ឈប់","Restart":"ចាប់ផ្តើមឡើងវិញ",
    "No servers match your search.":"រកមិនឃើញម៉ាស៊ីនដែលត្រូវនឹងការស្វែងរកទេ។",
    "General":"ទូទៅ","Console":"កុងសូល","Management":"ការគ្រប់គ្រង","Files":"ឯកសារ","Backups":"ការបម្រុងទុក","Domains":"ដែន","Deploy":"ដាក់ដំណើរការ",
    "Configuration":"ការកំណត់រចនាសម្ព័ន្ធ","Startup":"ការចាប់ផ្តើម","Settings":"ការកំណត់","Server stats":"ស្ថិតិម៉ាស៊ីន",
    "Subscription Information":"ព័ត៌មានការជាវ","Status:":"ស្ថានភាព៖","Expires:":"ផុតកំណត់៖","Plan:":"គម្រោង៖","Price:":"តម្លៃ៖","Service Link:":"តំណសេវាកម្ម៖",
    "View Service":"មើលសេវាកម្ម","Server Info":"ព័ត៌មានម៉ាស៊ីន","Uptime:":"រយៈពេលដំណើរការ៖","Type:":"ប្រភេទ៖","Server ID:":"លេខសម្គាល់ម៉ាស៊ីន៖",
    "CPU Usage:":"ការប្រើ CPU៖","Memory Usage:":"ការប្រើអង្គចងចាំ៖","Disk Usage:":"ការប្រើថាស៖","Active":"សកម្ម","Expired":"ផុតកំណត់",
    "View All":"មើលទាំងអស់","Info":"ព័ត៌មាន","Errors":"កំហុស","Type a command...":"វាយពាក្យបញ្ជា...","No logs yet.":"មិនទាន់មាន log ទេ។",
    "File Manager":"កម្មវិធីគ្រប់គ្រងឯកសារ","Search":"ស្វែងរក","Create Directory":"បង្កើតថត","Upload":"ផ្ទុកឡើង","New file":"ឯកសារថ្មី","Unarchive":"ពន្លាឯកសារ",
    "Download":"ទាញយក","name":"ឈ្មោះ","size":"ទំហំ","date":"កាលបរិច្ឆេទ","This folder is empty.":"ថតនេះទទេ។","Drop files here to upload":"ទម្លាក់ឯកសារនៅទីនេះដើម្បីផ្ទុកឡើង",
    "Manage backups":"គ្រប់គ្រងការបម្រុងទុក","Create backup":"បង្កើតការបម្រុងទុក","Restore":"ស្តារ","No backups yet.":"មិនទាន់មានការបម្រុងទុកទេ។",
    "Start command":"ពាក្យបញ្ជាចាប់ផ្តើម","Port":"ច្រក","Start automatically":"ចាប់ផ្តើមដោយស្វ័យប្រវត្តិ","Restart if it crashes":"ចាប់ផ្តើមឡើងវិញពេលគាំង",
    "Save changes":"រក្សាទុកការកែប្រែ","Environment variables":"អថេរបរិស្ថាន","Add":"បន្ថែម","Update":"ធ្វើបច្ចុប្បន្នភាព","Delete":"លុប","No variables yet.":"មិនទាន់មានអថេរទេ។",
    "Show values":"បង្ហាញតម្លៃ","Hide values":"លាក់តម្លៃ",
    "Add custom domain":"បន្ថែមដែនផ្ទាល់ខ្លួន","Add Domain":"បន្ថែមដែន","Verify":"ផ្ទៀងផ្ទាត់","Remove":"ដកចេញ","No domains yet.":"មិនទាន់មានដែនទេ។",
    "Git Deploy":"ដាក់ដំណើរការពី Git","Deploy from GitHub / Git":"ដាក់ដំណើរការពី GitHub / Git","Repository URL":"URL ឃ្លាំងកូដ","Branch":"សាខា","No deployments yet.":"មិនទាន់មានការដាក់ដំណើរការទេ។",
    "Change Server Details":"ប្តូរព័ត៌មានម៉ាស៊ីន","Server Name":"ឈ្មោះម៉ាស៊ីន","Domain / Subdomain":"ដែន / ដែនរង","Save":"រក្សាទុក","Connection":"ការតភ្ជាប់",
    "Debug Information":"ព័ត៌មានបច្ចេកទេស","Delete server":"លុបម៉ាស៊ីន","Delete service":"លុបសេវាកម្ម","Primary port":"ច្រកមេ","Hostname":"ឈ្មោះម៉ាស៊ីន","Status":"ស្ថានភាព",
    "Cancel":"បោះបង់","OK":"យល់ព្រម","Confirm":"បញ្ជាក់","Close":"បិទ","Rename":"ប្តូរឈ្មោះ","Copy":"ចម្លង","Move":"ផ្លាស់ទី","Edit":"កែសម្រួល","Discard":"បោះបង់ការកែ",
    "Saved":"បានរក្សាទុក","Unsaved changes":"មានការកែប្រែមិនទាន់រក្សាទុក","Discard unsaved changes?":"បោះបង់ការកែប្រែដែលមិនទាន់រក្សាទុកឬ?",
    "Start sent":"បានផ្ញើពាក្យបញ្ជាចាប់ផ្តើម","Stop sent":"បានផ្ញើពាក្យបញ្ជាបញ្ឈប់","Restart sent":"បានផ្ញើពាក្យបញ្ជាចាប់ផ្តើមឡើងវិញ","Uploaded":"បានផ្ទុកឡើង",
    "Uploaded & extracted":"បានផ្ទុកឡើង និងពន្លា","Deleted":"បានលុប","Renamed":"បានប្តូរឈ្មោះ","Copied":"បានចម្លង","Moved":"បានផ្លាស់ទី","File created":"បានបង្កើតឯកសារ",
    "Logs cleared":"បានសម្អាត log","Copy failed":"ចម្លងមិនបាន","Backup created":"បានបង្កើតការបម្រុងទុក","Backup deleted":"បានលុបការបម្រុងទុក","Restored":"បានស្តារ",
    "Domain added":"បានបន្ថែមដែន","Verified":"បានផ្ទៀងផ្ទាត់","Removed":"បានដកចេញ","Deployed":"បានដាក់ដំណើរការ","Deploy failed":"ការដាក់ដំណើរការបរាជ័យ",
    "Variable saved":"បានរក្សាទុកអថេរ","Variable deleted":"បានលុបអថេរ","Select a file to download":"សូមជ្រើសរើសឯកសារដើម្បីទាញយក","Select files first":"សូមជ្រើសរើសឯកសារជាមុន",
    "Clear all logs?":"សម្អាត log ទាំងអស់?","Remove domain?":"ដកដែននេះចេញ?","Delete this service? This cannot be undone.":"លុបសេវាកម្មនេះ? មិនអាចត្រឡប់វិញបានទេ។",
    "File name":"ឈ្មោះឯកសារ","Directory name":"ឈ្មោះថត","New name":"ឈ្មោះថ្មី","Destination folder":"ថតគោលដៅ","Create":"បង្កើត","Extract":"ពន្លា",
    "Download backup":"ទាញយកការបម្រុងទុក","Pause":"ផ្អាក","Auto-scroll":"រំកិលស្វ័យប្រវត្តិ"
  });

  const KEY = "aj_lang";
  const orig = new WeakMap();
  let lang = localStorage.getItem(KEY) || "en";
  let busy = false;

  window.__t = s => (lang === "km" && KM[s]) ? KM[s] : s;

  function tr(s) { const t = s.trim(); return KM[t] ? s.replace(t, KM[t]) : null; }

  function apply(root) {
    busy = true;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: n => /^(SCRIPT|STYLE|TEXTAREA)$/.test(n.parentNode.nodeName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
    });
    const nodes = []; while (w.nextNode()) nodes.push(w.currentNode);
    nodes.forEach(n => {
      if (!n.nodeValue.trim()) return;
      if (lang === "km") {
        const t = tr(orig.has(n) ? orig.get(n) : n.nodeValue);
        if (t !== null) { if (!orig.has(n)) orig.set(n, n.nodeValue); n.nodeValue = t; }
      } else if (orig.has(n)) { n.nodeValue = orig.get(n); orig.delete(n); }
    });
    root.querySelectorAll("[placeholder]").forEach(el => {
      if (!el.dataset.ph) el.dataset.ph = el.placeholder;
      el.placeholder = lang === "km" ? (KM[el.dataset.ph] || el.dataset.ph) : el.dataset.ph;
    });
    document.documentElement.lang = lang === "km" ? "km" : "en";
    busy = false;
  }

  function setLang(l) {
    lang = l; localStorage.setItem(KEY, l); apply(document.body);
    document.querySelectorAll(".lang-btn").forEach(b => b.textContent = l === "km" ? "EN" : "ខ្មែរ");
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".lang-btn").forEach(b => b.onclick = () => setLang(lang === "km" ? "en" : "km"));
    setLang(lang);
    let t; new MutationObserver(() => { if (busy || lang !== "km") return; clearTimeout(t); t = setTimeout(() => apply(document.body), 60); })
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  });
})();
