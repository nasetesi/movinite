package org.movinite.app;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

/** Every 6 hours (and on app start): renew licences, apply revocations, send offline deletes and watch progress. */
public class SyncWorker extends Worker {
    public SyncWorker(@NonNull Context c, @NonNull WorkerParameters p) { super(c, p); }

    @NonNull
    @Override
    public Result doWork() {
        Offline off = Offline.get(getApplicationContext());
        if (off.windowExpired()) { off.wipe("offline for too long"); return Result.success(); }
        if (!off.registered()) return Result.success();
        try { off.sync(); return Result.success(); }
        catch (Offline.ApiException e) { return e.code >= 500 ? Result.retry() : Result.success(); }
        catch (Exception e) { return Result.retry(); }
    }
}
