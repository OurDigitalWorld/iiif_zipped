"""
prep_iiif.py - create zipped tiles with cache for byte range requests

Usage (see list of options):
    prep_iiif.py [-h] 

This script walks through a directory of images and creates two new
directories with the same folder structure. Each image will have a 
corresponding tiles.zip file in one of the new paths based on the image 
file name. The other path will have the zipped file's dir structure
in a small binary file. The idea is that the tiles folders will be
stored on web storage but an intermediate process on a web server
will optionally use the dir file to look up a requested tile and
then obtain it with a byte range request.

The purpose of this approach is to avoid a gazillion files on a web
storage service for serving tiles while, at the same time, not
requiring an image server to carve up tiles dynamically. The process 
is described in some detail here:

    https://github.com/OurDigitalWorld/iiif_zipped

This is a work-in-progress but the hope is to find a low-cost solution
for resource constrained server environments. The resulting tiles.zip
files do not use compression (since we want to minimize on the work
that the web server performs), but they go gain efficiencies from
avoiding the sometimes astounding number of nested directories in
a typical IIIF rendering.

- art rhyno, u. of windsor & ourdigitalworld
"""
import bitstring
import glob, os, re, sys, tempfile
import json
import optparse
from pathlib import Path
from PIL import Image
from subprocess import call
import struct
import zipfile

RESIZE = 1.5 # we typically upsize an image before tiling, this could be downsized if needed
IIIF_STATIC = "./iiif_static.py" # see https://github.com/zimeon/iiif
IIIF_OPTS = "-e '/full/90,/0/default.jpg' -e '/full/200,/0/default.jpg'" # add extra options here
ZIP_MARKER = "0x504b0506" # signature for end of zip central directory record

""" sort_out_json - take incoming image info and finalize IIIF manifest """
def sort_out_json(out_folder, obj_folder, imgs, json_imgs):

    last_pg = len(imgs) - 1 # calculate last page based on images
    json_obj = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": obj_folder + "/manifest.json",
        "label" : "",
        "description" : "",
        "logo" : "",
        "sequences": [
            {
                "@type": "sc:Sequence",
                "canvases": json_imgs
            }
        ],
        "structures": [
            {
                "@id": imgs[0] + "/ranges/1",
                "@type": "sc:Range",
                "label": "Front Page",
                "canvases": [
                    imgs[0] + "/canvas/1"
                ],
                "within": ""
            },
            {
                "@id": imgs[last_pg] + "/ranges/" + str(last_pg + 1),
                "@type": "sc:Range",
                "label": "Last Page",
                "canvases": [
                    imgs[last_pg] + "/canvas/" + str(last_pg + 1)
                ],
                "within": ""
            }
        ]
    }

    json_dump = json.dumps(json_obj, indent=4)
    with open(out_folder + "/manifest.json", "w") as outfile:
        outfile.write(json_dump)

""" resize_by_mult - use multiple to resize image """
def resize_by_mult(image, mult):
    with Image.open (image) as im:
        width, height = im.size
        resized_dimensions = (int(width * mult), int(height * mult))
        resized = im.resize(resized_dimensions)
        width, height = resized.size
        return width, height, resized
    return 0, 0, None

""" zipdir - add to zip archive, put files in tiles folder """
def zipdir(path, ziph):
    for root, dirs, files in os.walk(path):
        for file in files:
            tile_file = os.path.join(root, file)
            out_file = tile_file.replace(path,"tiles")
            ziph.write(tile_file,out_file)

""" sort_out_zipdir - extract zip directory from archive """
def sort_out_zipdir(dir_loc,zip_file,dir_file):

    Path(dir_loc).mkdir(parents=True, exist_ok=True) # create folder structure

    zfile = open(zip_file,"rb")
    bin_stream = bitstring.ConstBitStream(zfile) # use bitstring to handle binary 
    bin_stream.find(ZIP_MARKER)
    bin_buffer = bin_stream.read("bytes:12") # move to position
    bin_buffer = bin_stream.read("bytes:4") # zip dir specs
    zip_dir_size = struct.unpack("<L",bin_buffer)[0]
    bin_buffer = bin_stream.read("bytes:4")
    zip_offset = struct.unpack("<L",bin_buffer)[0]
    zfile.close() # close stream

    zfile = open(zip_file,"rb") # reopen for clean start
    zfile.seek(zip_offset,0) # search from start using offset
    zip_dir_data = zfile.read(zip_dir_size)

    with open(dir_file,"wb") as f:
        f.write(zip_dir_data) # write out zip dir
                
""" sort_out_zip - pull together archive """
def sort_out_zip(ofolder, identifier, temp_dir):
    info_json = temp_dir + "/info.json"

    if os.path.exists(info_json): # info.json is created by tiles process
        contents = ""

        with open(info_json, 'r') as info_json_file:
            contents = info_json_file.read().replace(temp_dir,identifier)
            info_json_file.close()
            zip_cloud_loc = ofolder + "/cloud" + identifier
            zip_cache_loc = ofolder + "/cache" + identifier
            zip_file = ofolder + "/cloud" + identifier + '/tiles.zip'
            dir_file = ofolder + "/cache" + identifier + '/dir.bin'

            if len(contents) > 0:
                info_json_file = open(info_json,"w")
                info_json_file.write(contents)
                info_json_file.close()
                Path(zip_cloud_loc).mkdir(parents=True, exist_ok=True)
                zipf = zipfile.ZipFile(zip_file, 'w', compression=zipfile.ZIP_STORED, 
                        allowZip64=False, compresslevel=None)
                zipdir(temp_dir, zipf)
                zipf.close()

            if os.path.exists(zip_file):
                sort_out_zipdir(zip_cache_loc,zip_file,dir_file)

""" proc_image_folder - build image collection into IIIF layout """
def proc_image_folder(iroot,ifolder,ofolder):

    imgs = []
    json_imgs = []

    img_path = ifolder.replace(iroot,"")
    img_list = glob.glob(ifolder + '/*') # assuming everything in directory is image
    img_list = sorted(img_list)
    pg_no = 1

    for img in img_list:
        img_bits = os.path.splitext(img.replace(ifolder + "/",""))
        dir_bits = os.path.splitext(img.replace(iroot,""))
        w, h, target_img = resize_by_mult(img,RESIZE) # TODO: make resize optional
        tf = tempfile.NamedTemporaryFile()
        temp_file_name = tf.name
        target_img.save(temp_file_name, "JPEG") # save resized file in JPEG

        # cloud directory is what will hold zips destined for web storage 
        img_folder = ofolder + "/cloud" + img_path
        identifier = img_path + "/" + img_bits[0]
        imgs.append(identifier)
        if not os.path.exists(img_folder):
            Path(img_folder).mkdir(parents=True, exist_ok=True)

        if not os.path.exists(ofolder + "/cloud" + identifier):
            td = tempfile.TemporaryDirectory(dir='')
            # we run IIIF tile cutting as shell process - this can be slow
            cmd_line = "python %s -i '%s' " % (IIIF_STATIC,td.name)
            cmd_line += IIIF_OPTS
            cmd_line += (" -d '.' %s" % temp_file_name)
            call(cmd_line, shell=True)
            sort_out_zip(ofolder,identifier, td.name)
            td.cleanup() # we don't keep resulting tiles anywhere but archive

        # add image info in bare-bones IIIF format
        json_imgs.append({ "@type": "sc:Canvas",
            "@id": identifier + "/canvas/" + str(pg_no),
            "label": "Pg. " + str(pg_no),
            "width": w,
            "height": h,
            "images": [
                {
                    "@type": "oa:Annotation",
                    "motivation": "sc:painting",
                    "on": identifier + "/canvas/" + str(pg_no),
                    "resource": {
                        "@type": "dctypes:Image",
                        "@id": identifier + "/full/103,/0/default.jpg",
                            "service": {
                                "@context":  "http://iiif.io/api/image/2/context.json",
                                "@id": identifier, 
                                "profile": "http://iiif.io/api/image/2/level2.json"
                             }
                     }
                }
            ]})
        pg_no += 1
        tf.close()

    sort_out_json(img_folder, img_path, imgs, json_imgs) # images are ready to pass to manifest

    return True

p = optparse.OptionParser(description='Process image files for cnode',
    usage='usage: %prog [options] folder (-h for help)')
p.add_option('--dst', '-d', action='store', default='',
    help="Destination directory for output")
p.add_option('--folder', '-f', action='store', default='',
    help="Input directory")

(opt,_) = p.parse_args()

if (len(opt.folder) == 0 or len(opt.dst) == 0):
    print("missing directory information, exiting...")
    quit()

root_list = glob.glob(opt.folder)
for root in root_list:
    print("root ->", root)
    folder_list = glob.glob(root + '/*')
    folder_list = sorted(folder_list)
    for folder in folder_list:
        print("folder -->", folder)
        sub_folder_list = glob.glob(folder + '/*')
        sub_folder_list = sorted(sub_folder_list)
        for sub_folder in sub_folder_list:
            print("subfolder --->", sub_folder)
            if not proc_image_folder(root,sub_folder,opt.dst):
                print("problem!")
                quit()
