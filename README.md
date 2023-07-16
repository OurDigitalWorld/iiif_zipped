# iiif_zipped
This project attempts to leverage [byte ranges](https://en.wikipedia.org/wiki/Byte_serving)
and the [ZIP file format](https://en.wikipedia.org/wiki/ZIP_(file_format)) to simplify the handling
of precut [IIIF](https://iiif.io/) tiles on web storage. It consists of two scripts, one in python
and one in php. Due to resource constraints, our approach to digitization services has typically
been to "process in python" and "serve in php", in both cases reflecting the environments we have
access to for each. The python script has the following options:
```
Usage: prep_iiif.py [options] folder (-h for help)

Process image files for cnode

Options:
  -h, --help            show this help message and exit
  -d DST, --dst=DST     Destination directory for output
  -f FOLDER, --folder=FOLDER
                        Input directory
```
We are currently using a simple folder layout for many of collections. A typical example would be
as follows:
```
$ ls sample/intro/letter/
Vol_1_Intro_0001.tif  Vol_1_Intro_0002.tif  Vol_1_Intro_0003.tif
```
In this case, we want to serve the images to IIIF viewers. To prepare the images, we could
issue this command:
```
$ python prep_iiif.py -f sample -d demo
```
The script will go through each image, invoke a [tile cutter](https://github.com/zimeon/iiif)
to parcel it up into tiles, and then store those tiles in a ZIP archive called _tiles.zip_, as
well as storing the directory of the zip archive in a file called _dir.bin_. The
location of these files will reflect the layout of the collection:
```
$ ls demo
cache  cloud
$ ls demo/cache/letter/Vol_1_Intro_0001
dir.bin
$ ls demo/cloud/letter/Vol_1_Intro_0001
tiles.zip
```
The contents of the _cloud_ folder will be uploaded to cloud storage, and the contents of the 
_cache_ folder will be put on a location accessible to the php script. Rudimentary versions
of the IIIF _manifest.json_ and _info.json_ will be created according to each folder. The 
_cache_ is optional. If it's not used, the php script will end up making 4 calls to the web 
storage provider on the first call:
1. URL to get file size of the ZIP archive (the key information needed is near the end
   of the file so the size allows the offset to be calculated)
3. URL to extract the end portion of the ZIP archive to get the _end of directory_ record
4. URL to extract ZIP directory from ZIP archive using byte range based on the _end of directory_ record
5. URL to extract desired file from ZIP archive using byte range (either tile request of _info.json_ file)

The directory will be added to an [APC](http://php.adamharvey.name/manual/en/book.apc.php) cache. For Ubuntu,
this might mean installing APC if it's not already there:
```
sudo apt-get install php-apcu
```
Restart Apache afterwards. If you do things at the command line, you seem to need to tell PHP that APC is enabled:
```
php -d apc.enable_cli=1 ./iiif_zipper.php
```
The file system _cache_ is a copy of the ZIP directory. If present on the same file system as the php script, 
the php script will read the directory and make one call to web storage with the byte range for 
the requested file. Depending on network bandwidth, this might provide a significantly faster 
response. The glue that holds this together is the ZIP directory format, these two web pages
have been extremely helpful in sorting out this mechanism:
* https://docs.fileformat.com/compression/zip/
* https://users.cs.jmu.edu/buchhofp/forensics/formats/pkzip.html

In addition to tiles, two IIIF json files go through the php script as well. These are
the _manifest.json_ file and the _info.json_ file. The whole process is
brought together with URLs like the following:
```
iiif_zipper.php?path=/intro/letter/manifest.json
iiif_zipper.php?path=/essex/1971-08-04/manifest.json
```
For example, [a newspaper issue served as a IIIF resource](https://collections.uwindsor.ca/login/iiif/uv/uv.html#?manifest=/login/iiif/iiif_zipper.php?path=/essex/1971-08-04/manifest.json).
We want the json files to go through the script in order to add implementation details,
such that syntax like this:
```
"@id": "/intro/letter/Vol_1_Intro_0001/canvas/1",
"label": "Pg. 1",
```
is transformed into this:
```
"@id": "/iiif_zipper.php?path=/intro/letter/Vol_1_Intro_0001/canvas/1",
"label": "Pg. 1",
```
The idea is that the web storage holds a pristine copy of the folder layout
but the implementation details are added on the fly. Another approach
is to use JavaScript to do the IIIF calls using byte-ranges, the
file _iiif_zipper_js.html_ shows one example of this, which is 
[deployed here](https://collections.uwindsor.ca/login/iiif/iiif_zipper_js.html).
We are still in the early days of working out how best to structure IIIF support
with modest server resources. Our deepest thanks to [Peter Binkley](https://pbinkley.github.io/) 
at the [University of Alberta Library](https://www.library.ualberta.ca/) for helping us 
navigate _manifest.json_ options. 
