package pk.quantofrehan;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.IBinder;

/**
 * Thin facade kept so the manifest has a service entry; all real work
 * happens in Watcher. Started on app open and from the boot receiver.
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

    static void armAlarms(Context c) {
        Watcher.armAlarms(c);
    }

    interface Callback {
        void done(boolean online, boolean reachable, String detail,
                  String signals, Watcher.Market market);
    }

    static void fetchStatus(Context c, String admin, Callback cb) {
        Watcher.fetchStatus(c, admin, cb::done);
    }
}
