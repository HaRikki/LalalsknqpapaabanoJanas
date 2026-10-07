Apsara deploy — ត្រូវតែមាន files នៅ ROOT container (មិនមែនក្នុង folder anajak-host)

ត្រូវឃើញ:
  app.py
  start.sh
  requirements.txt
  core/
  templates/
  static/
  scripts/
  .env

កុំ Move/Delete folders បន្ទាប់ពី Unarchive។

1) លុប files ចាស់ក្នុង container (ឬ container ទទេ)
2) Upload zip នេះ
3) Unarchive
4) បើមាន folder anajak-host ក្រៅ — ខុស zip។ zip នេះ extract ផ្ទាល់ជា app.py នៅ root
5) Start server (ប៊ូតុង Play)
6) បើក https://angker-smm.ndclub.top/login
