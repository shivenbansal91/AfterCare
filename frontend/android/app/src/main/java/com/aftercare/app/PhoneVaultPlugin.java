package com.aftercare.app;

import android.content.Intent;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;
import androidx.core.content.FileProvider;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileNotFoundException;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

@CapacitorPlugin(name = "PhoneVault")
public class PhoneVaultPlugin extends Plugin {
    private static final String KEY = "aftercare-phone-v1";

    private AtomicFile vault() {
        return new AtomicFile(new File(getContext().getNoBackupFilesDir(), "aftercare-v1.bin"));
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(KEY)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY, null);
    }

    @PluginMethod
    public synchronized void load(PluginCall call) {
        try {
            JSObject result = new JSObject();
            byte[] sealed;
            try {
                sealed = vault().readFully();
            } catch (FileNotFoundException missing) {
                result.put("value", JSONObject.NULL);
                call.resolve(result);
                return;
            }
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOfRange(sealed, 0, 12)));
            result.put("value", new String(cipher.doFinal(sealed, 12, sealed.length - 12), StandardCharsets.UTF_8));
            call.resolve(result);
        } catch (Exception error) {
            call.reject("The phone's encrypted records could not be unlocked. Your server records are unchanged.", error);
        }
    }

    @PluginMethod
    public synchronized void save(PluginCall call) {
        FileOutputStream output = null;
        try {
            String value = call.getString("value");
            if (value == null || value.length() > 8_000_000) throw new IllegalArgumentException("Invalid snapshot size");
            new JSONObject(value);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            output = vault().startWrite();
            output.write(cipher.getIV());
            output.write(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)));
            vault().finishWrite(output);
            call.resolve();
        } catch (Exception error) {
            if (output != null) vault().failWrite(output);
            call.reject("The recording could not be saved securely on this phone. Please try again.", error);
        }
    }

    @PluginMethod
    public synchronized void clear(PluginCall call) {
        vault().delete();
        call.resolve();
    }

    @PluginMethod
    public void openFile(PluginCall call) {
        try {
            String name = call.getString("name", "aftercare-document.pdf").replaceAll("[^a-zA-Z0-9._-]", "_");
            File folder = new File(getContext().getCacheDir(), "aftercare-exports");
            folder.mkdirs();
            File file = new File(folder, name);
            byte[] bytes = Base64.decode(call.getString("data", ""), Base64.DEFAULT);
            try (FileOutputStream output = new FileOutputStream(file)) {
                output.write(bytes);
            }
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", file), call.getString("mime", "application/pdf"));
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            getActivity().startActivity(intent);
            call.resolve();
        } catch (Exception error) {
            call.reject("The document could not be opened. Check that a compatible viewer is installed.", error);
        }
    }
}
