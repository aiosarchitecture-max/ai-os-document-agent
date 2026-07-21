# AI_OS – oprava Google Apps Script presmerovania

Balík obsahuje iba dva otestované súbory:

- `app/services.py`
- `tests/test_core.py`

Obsah priečinka `rebuild` skopírujte do koreňa lokálneho repozitára `ai-os-document-agent` vo vetve `agent/ai-os-core-rebuild`. Pri otázke Windows zvoľte nahradenie súborov. GitHub Desktop musí potom ukázať presne 2 zmenené súbory.

Oprava povoľuje štandardné Google presmerovanie `302` z `script.google.com` na `script.googleusercontent.com`. Neobsahuje tokeny, URL deploymentu ani tajomstvá.
