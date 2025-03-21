#!/usr/bin/env python


__license__   = 'GPL v3'
__copyright__ = '2012, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os
import sys
import unicodedata

from calibre import as_unicode, prints, walk
from calibre.constants import __appname__, iswindows
from calibre.libunzip import extract as zipextract
from calibre.ptempfile import TemporaryDirectory
from calibre.utils.ipc.simple_worker import WorkerError
from calibre.utils.zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


class Error(ValueError):
    pass


def ask_cli_question(msg):
    prints(msg, end=' [y/N]: ')
    sys.stdout.flush()

    if iswindows:
        import msvcrt
        ans = msvcrt.getch()
    else:
        import termios
        import tty
        old_settings = termios.tcgetattr(sys.stdin.fileno())
        try:
            tty.setraw(sys.stdin.fileno())
            try:
                ans = sys.stdin.read(1)
            except KeyboardInterrupt:
                ans = b''
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
    print()
    return ans == b'y'


def mobi_exploder(path, tdir, question=lambda x:True):
    from calibre.ebooks.mobi.tweak import BadFormat, explode
    try:
        return explode(path, tdir, question=question)
    except BadFormat as e:
        raise Error(as_unicode(e))


def zip_exploder(path, tdir, question=lambda x:True):
    zipextract(path, tdir)
    for f in walk(tdir):
        if f.lower().endswith('.opf'):
            return f
    raise Error('Invalid book: Could not find .opf')


def zip_rebuilder(tdir, path):
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as zf:
        # Write mimetype
        mt = os.path.join(tdir, 'mimetype')
        if os.path.exists(mt):
            zf.write(mt, 'mimetype', compress_type=ZIP_STORED)
        # Write everything else
        exclude_files = {'.DS_Store', 'mimetype', 'iTunesMetadata.plist'}
        for root, dirs, files in os.walk(tdir):
            for fn in files:
                if fn in exclude_files:
                    continue
                absfn = os.path.join(root, fn)
                zfn = unicodedata.normalize('NFC', os.path.relpath(absfn, tdir).replace(os.sep, '/'))
                zf.write(absfn, zfn)


def docx_exploder(path, tdir, question=lambda x:True):
    zipextract(path, tdir)
    from calibre.ebooks.docx.dump import pretty_all_xml_in_dir
    pretty_all_xml_in_dir(tdir)
    for f in walk(tdir):
        if os.path.basename(f) == 'document.xml':
            return f
    raise Error('Invalid book: Could not find document.xml')


def get_tools(fmt):
    fmt = fmt.lower()

    if fmt in {'mobi', 'azw', 'azw3'}:
        from calibre.ebooks.mobi.tweak import rebuild
        ans = mobi_exploder, rebuild
    elif fmt in {'epub', 'htmlz'}:
        ans = zip_exploder, zip_rebuilder
    elif fmt == 'docx':
        ans = docx_exploder, zip_rebuilder
    else:
        ans = None, None

    return ans


def explode(ebook_file, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if not os.path.isdir(output_dir):
        raise SystemExit(f'{output_dir} is not a directory')
    output_dir = os.path.abspath(output_dir)
    fmt = ebook_file.rpartition('.')[-1].lower()
    exploder, rebuilder = get_tools(fmt)
    if exploder is None:
        raise SystemExit(f'Cannot tweak {fmt.upper()} files. Supported formats are: EPUB, HTMLZ, AZW3, MOBI, DOCX')
    try:
        opf = exploder(ebook_file, output_dir, question=ask_cli_question)
    except WorkerError as e:
        prints('Failed to unpack', ebook_file)
        prints(e.orig_tb)
        raise SystemExit(1)
    except Error as e:
        prints(as_unicode(e), file=sys.stderr)
        raise SystemExit(1)

    if opf is None:
        # The question was answered with No
        return
    h = '_' if iswindows else '.'
    with open(os.path.join(output_dir, h + '__explode_fmt__'), 'wb') as f:
        f.write(fmt.encode('utf-8'))
    prints('Book extracted to', output_dir)
    prints('Make your changes and once you are done, use --implode-book to rebuild')


def implode(output_dir, ebook_file):
    output_dir = os.path.abspath(output_dir)
    fmt = ebook_file.rpartition('.')[-1].lower()
    exploder, rebuilder = get_tools(fmt)
    if rebuilder is None:
        raise SystemExit(f'Cannot tweak {fmt.upper()} files. Supported formats are: EPUB, HTMLZ, AZW3, MOBI, DOCX')
    h = '_' if iswindows else '.'
    efmt_path = os.path.join(output_dir, h + '__explode_fmt__')
    try:
        with open(efmt_path, 'rb') as f:
            efmt = f.read().decode('utf-8')
    except Exception:
        raise SystemExit(f'The folder {output_dir} does not seem to have been created by --explode-book')
    if efmt != fmt:
        raise SystemExit('You must use the same format of file as was used when exploding the book')
    os.remove(efmt_path)
    try:
        rebuilder(output_dir, ebook_file)
    except WorkerError as e:
        prints('Failed to rebuild', ebook_file)
        prints(e.orig_tb)
        raise SystemExit(1)
    prints(ebook_file, 'successfully rebuilt')


def tweak(ebook_file):
    ''' Command line interface to the Tweak Book tool '''
    fmt = ebook_file.rpartition('.')[-1].lower()
    exploder, rebuilder = get_tools(fmt)
    if exploder is None:
        prints(f'Cannot tweak {fmt.upper()} files. Supported formats are: EPUB, HTMLZ, AZW3, MOBI'
                , file=sys.stderr)
        raise SystemExit(1)

    with TemporaryDirectory('_tweak_'+
            os.path.basename(ebook_file).rpartition('.')[0]) as tdir:
        try:
            opf = exploder(ebook_file, tdir, question=ask_cli_question)
        except WorkerError as e:
            prints('Failed to unpack', ebook_file)
            prints(e.orig_tb)
            raise SystemExit(1)
        except Error as e:
            prints(as_unicode(e), file=sys.stderr)
            raise SystemExit(1)

        if opf is None:
            # The question was answered with No
            return

        prints('Book extracted to', tdir)
        prints('Make your tweaks and once you are done,', __appname__,
                'will rebuild', ebook_file, 'from', tdir)
        print()
        proceed = ask_cli_question('Rebuild ' + ebook_file + '?')

        if proceed:
            prints('Rebuilding', ebook_file, 'please wait ...')
            try:
                rebuilder(tdir, ebook_file)
            except WorkerError as e:
                prints('Failed to rebuild', ebook_file)
                prints(e.orig_tb)
                raise SystemExit(1)
            prints(ebook_file, 'successfully tweaked')
