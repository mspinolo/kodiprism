#!/usr/bin/env python3
"""Create small JPEG photos with known EXIF dates for tests against a real PhotoPrism.

    python3 tools/make_test_photos.py <originals dir>

Each photo has a different colour/noise (so PhotoPrism does not treat them as duplicates) and an EXIF
DateTimeOriginal, so the expected "date of the newest photo" of every test album is known in advance.
Requires: pip install pillow piexif
"""
import os
import random
import sys

import piexif
from PIL import Image

# folder -> list of (file name, taken at)
PHOTOS = {
    "2008-bretagna": [("IMG_0001.jpg", "2008:08:02 10:00:00"), ("IMG_0002.jpg", "2008:08:03 11:30:00"), ("IMG_0003.jpg", "2008:08:05 09:15:00")],
    "2019-roma": [("IMG_0101.jpg", "2019:03:10 15:00:00"), ("IMG_0102.jpg", "2019:03:12 18:45:00")],
    "2015-cafe": [("IMG_0201.jpg", "2015:07:01 08:00:00"), ("IMG_0202.jpg", "2015:07:02 21:10:00")],
    "sparse": [("IMG_0301.jpg", "2020:11:23 12:00:00"), ("IMG_0302.jpg", "2022:11:23 13:00:00"), ("IMG_0303.jpg", "2022:01:05 14:00:00")],
}


def make(path, taken, seed):
    rnd = random.Random(seed)
    base = tuple(rnd.randint(20, 235) for _ in range(3))
    img = Image.new("RGB", (640, 480), base)
    px = img.load()
    for _ in range(4000):  # noise: distinct content per photo
        px[rnd.randrange(640), rnd.randrange(480)] = tuple(rnd.randint(0, 255) for _ in range(3))
    exif = piexif.dump({"Exif": {piexif.ExifIFD.DateTimeOriginal: taken.encode(), piexif.ExifIFD.DateTimeDigitized: taken.encode()},
                        "0th": {piexif.ImageIFD.Make: b"KodiPrismTest", piexif.ImageIFD.Model: b"CI-Camera"}})
    img.save(path, "JPEG", quality=85, exif=exif)


def main(out):
    n = 0
    for folder, items in PHOTOS.items():
        os.makedirs(os.path.join(out, folder), exist_ok=True)
        for name, taken in items:
            n += 1
            make(os.path.join(out, folder, name), taken, seed=n)
    print("created %d photos in %s" % (n, out))


def bulk(out, n):
    """n small unique photos, one per hour from 2023-01-01 (newer than every photo of PHOTOS)."""
    import datetime
    folder = os.path.join(out, "bulk")
    os.makedirs(folder, exist_ok=True)
    t0 = datetime.datetime(2023, 1, 1, 0, 0, 0)
    for i in range(n):
        taken = (t0 + datetime.timedelta(hours=i)).strftime("%Y:%m:%d %H:%M:%S")
        rnd = random.Random(100000 + i)
        img = Image.new("RGB", (160, 120), tuple(rnd.randint(20, 235) for _ in range(3)))
        px = img.load()
        for _ in range(300):
            px[rnd.randrange(160), rnd.randrange(120)] = tuple(rnd.randint(0, 255) for _ in range(3))
        exif = piexif.dump({"Exif": {piexif.ExifIFD.DateTimeOriginal: taken.encode(), piexif.ExifIFD.DateTimeDigitized: taken.encode()},
                            "0th": {piexif.ImageIFD.Make: b"KodiPrismBulk", piexif.ImageIFD.Model: b"CI-Bulk"}})
        img.save(os.path.join(folder, "B%05d.jpg" % i), "JPEG", quality=80, exif=exif)
    print("created %d bulk photos in %s" % (n, folder))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--bulk":
        bulk(sys.argv[3] if len(sys.argv) > 3 else "test-photos", int(sys.argv[2]))
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "test-photos")
