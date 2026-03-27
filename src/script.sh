#!/bin/bash

# Percorso della cartella contenente gli APK (modifica con il percorso giusto)
APK_DIRECTORY="/home/x3no21/apks"

# Opzioni di obfuscazione senza dex method limit (65k)
OBFUSCATION_OPTIONS="-o ResStringEncryption -o Rebuild -o NewAlignment -o NewSignature"

# Itera su tutti i file .apk nella cartella specificata
for apk in "$APK_DIRECTORY"/*.apk; do
    if [ -f "$apk" ]; then
        echo "Eseguendo obfuscazione su: $apk"
        # Rimuove la cache fallata di apktool per forzare al plugin Rebuild di ricreare il framework corretto ogni volta
        rm -f /tmp/1.apk
        /home/x3no21/.pyenv/versions/obfuscapk_venv/bin/python3 -m obfuscapk.cli -p -i $OBFUSCATION_OPTIONS "$apk"
        if [ $? -ne 0 ]; then
            echo "Errore durante l'esecuzione di obfuscapk su $apk"
        else
            echo "Obfuscazione completata per: $apk"
        fi
    fi
done
