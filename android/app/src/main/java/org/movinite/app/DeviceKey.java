package org.movinite.app;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;

import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;

/** This phone's identity for downloads: an EC P-256 key made inside the Android Keystore (the private half never leaves it). */
final class DeviceKey {
    static final String ALIAS = "movinite_device_v1";
    private DeviceKey() {}

    private static KeyStore ks() throws Exception { KeyStore k = KeyStore.getInstance("AndroidKeyStore"); k.load(null); return k; }

    static synchronized void create() throws Exception {
        delete();
        KeyPairGenerator g = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore");
        g.initialize(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(new ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .build());
        g.generateKeyPair();
    }

    static boolean exists() { try { return ks().containsAlias(ALIAS); } catch (Exception e) { return false; } }

    static void delete() { try { KeyStore k = ks(); if (k.containsAlias(ALIAS)) k.deleteEntry(ALIAS); } catch (Exception ignored) { } }

    /** X.509 SubjectPublicKeyInfo DER (what the server stores and fingerprints) */
    static byte[] publicDer() throws Exception {
        PublicKey p = ks().getCertificate(ALIAS).getPublicKey();
        return p.getEncoded();
    }

    /** DER ECDSA-SHA256 signature */
    static byte[] sign(byte[] msg) throws Exception {
        PrivateKey k = (PrivateKey) ks().getKey(ALIAS, null);
        if (k == null) throw new IllegalStateException("device key missing");
        Signature s = Signature.getInstance("SHA256withECDSA");
        s.initSign(k);
        s.update(msg);
        return s.sign();
    }
}
