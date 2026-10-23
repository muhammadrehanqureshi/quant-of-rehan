package pk.quantofrehan;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.IBinder;

/**
 * Thin facade kept so the manifest has a service entry; all real work
 * happens in Watcher. Started on app open (v2.2.1: the boot receiver is
 * gone with the watch window, so nothing starts this in the background).
 */
public class StatusService extends Service {

    static final String DEFAULT_RELAY = Watcher.DEFAULT_RELAY;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Watcher.kick(this);
        return START_NOT_STICKY;
    }

    static void kick(Context c) {
        Watcher.kick(c);
        c.startService(new Intent(c, StatusService.class));
    }

    interface Callback {
        void done(boolean online, boolean reachable, String detail,
                  String signals, Watcher.Market market);
    }

    static void fetchStatus(Context c, Callback cb) {
        // The phone holds no admin token since owner order 2026-10-19.
        Watcher.fetchStatus(c, cb::done);
    }
}
