// Тема до первой отрисовки: светлую ставим сразу, иначе при запуске мелькнула бы тёмная.
// Отдельным файлом, потому что политика безопасности запрещает встроенные скрипты.
try{document.documentElement.dataset.theme=localStorage.getItem('tag-theme')==='light'?'light':'dark';}catch(e){}
