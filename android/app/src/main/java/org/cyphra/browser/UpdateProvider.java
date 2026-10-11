/* MPL-2.0. Read-only grant for one verified update APK inside app-private cache. */
package org.cyphra.browser;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;

public final class UpdateProvider extends ContentProvider {
    public static Uri uri(android.content.Context context, File file) {
        String directory=file.getParentFile().getName();
        String mode=directory.equals("updates-work")?"work":directory.equals("updates-personal")?"personal":null;
        if(mode==null)throw new IllegalArgumentException("Invalid update directory.");
        return new Uri.Builder().scheme("content").authority(context.getPackageName()+".updates")
            .appendPath(mode).appendPath(file.getName()).build();
    }
    private File file(Uri uri) throws FileNotFoundException {
        if(!uri.getAuthority().equals(getContext().getPackageName()+".updates") || uri.getPathSegments().size()!=2)
            throw new FileNotFoundException("Invalid update URI.");
        String mode=uri.getPathSegments().get(0);
        if(!"work".equals(mode)&&!"personal".equals(mode))throw new FileNotFoundException("Invalid update mode.");
        String name=uri.getLastPathSegment();
        if(name==null || !name.matches("[A-Za-z0-9._-]+\\.apk")) throw new FileNotFoundException("Invalid update file.");
        File folder=new File(getContext().getCacheDir(),"updates-"+mode);
        File candidate=new File(folder,name);
        try {
            if(!candidate.getCanonicalFile().getParentFile().equals(folder.getCanonicalFile()) || !candidate.isFile())
                throw new FileNotFoundException("Update unavailable.");
        } catch(IOException error) {throw new FileNotFoundException("Update unavailable.");}
        return candidate;
    }
    @Override public boolean onCreate(){return true;}
    @Override public String getType(Uri uri){return "application/vnd.android.package-archive";}
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!"r".equals(mode)) throw new FileNotFoundException("Read-only update.");
        return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort) {
        try {
            File file=file(uri);
            MatrixCursor result=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});
            result.addRow(new Object[]{file.getName(),file.length()}); return result;
        } catch(FileNotFoundException error) {return null;}
    }
    @Override public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    @Override public int delete(Uri uri,String where,String[] args){throw new UnsupportedOperationException();}
    @Override public int update(Uri uri,ContentValues values,String where,String[] args){throw new UnsupportedOperationException();}
}
