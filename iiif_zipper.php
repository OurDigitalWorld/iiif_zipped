<?php
/*
 
iiif_zipper.php - respond to web requests for IIIF tiles

This script relies on web storage where byte range requests
are possible. The tiles are extracted from zip archives
that reside on the storage. Requests are in the format:

iiif_zipper.php?path=/dir1/dir2/manifest.json

The ZIP format used is described in these sources:

https://docs.fileformat.com/compression/zip/
https://users.cs.jmu.edu/buchhofp/forensics/formats/pkzip.html

For more details, see the documentation here:

https://github.com/OurDigitalWorld/iiif_zipped

- art rhyno, u. of windsor & ourdigitalworld
*/

$HOST = ""; //json files on web storage are rewritten to include server (if desired)
$SCRIPT = "/shim/dist2/iiif_zipper.php"; //include the path to the script
$ZIP_DIR_PATH = ""; //location of cached zip dirs (or empty)
$SCRIPT_PATH_LEN = 3; //depth of file layout, e.g: pub_code [1], date [2], page [3]
$WEB_STORAGE = "https://WEB_STORAGE_LOC"; //url of web storage

//zip format values, these should not need to be changed
$END_OF_DIR_SIGNATURE = "\x50\x4b\x05\x06"; //this should be near the end of the archive
$CENTRAL_DIR_START = 46; //we look for the file name, which starts in this position
$FILE_NAME_LEN_POS = 28; //position of file name len (always get this from directory!)
$EXTRA_FIELD_LEN_POS = 30; //positon of extra field len (if any)
$FIELD_COMMENT_LEN_POS = 32; //positon of field comment (if any)
$COMP_SIZE_POS = 20; //position of size of file (we don't deal with compression so matches original)
$REL_OFFSET_POS = 42; //offset from start of archive to local file header
$LOCAL_FILE_HEADER_LEN = 30; //length of local file header (which we will skip)
$END_OF_FILE_GAP = 500; //how far to start from end of archive to look for end of dir signature

/*
 * curl_get_file_size - get size of file on remote web server with one call
*/
//see https://stackoverflow.com/questions/2602612/remote-file-size-without-downloading-file
function curl_get_file_size( $url ) {
  // Assume failure.
  $result = -1;

  $curl = curl_init( $url );

  // Issue a HEAD request and follow any redirects.
  curl_setopt( $curl, CURLOPT_NOBODY, true );
  curl_setopt( $curl, CURLOPT_HEADER, true );
  curl_setopt( $curl, CURLOPT_RETURNTRANSFER, true );
  curl_setopt( $curl, CURLOPT_FOLLOWLOCATION, true );

  $data = curl_exec( $curl );
  curl_close( $curl );

  if( $data ) {
      $content_length = "unknown";
      $status = "unknown";

      if( preg_match( "/^HTTP\/1\.[01] (\d\d\d)/", $data, $matches ) ) {
          $status = (int)$matches[1];
      }//if

      if( preg_match( "/Content-Length: (\d+)/", $data, $matches ) ) {
          $content_length = (int)$matches[1];
      }//if

      // http://en.wikipedia.org/wiki/List_of_HTTP_status_codes
      if( $status == 200 || ($status > 300 && $status <= 308) ) {
          $result = $content_length;
      }//if
  }//if data

  return $result;
}//curl_get_file_size

/*
 * curl_get_range - make byte range request to web storage
*/
function curl_get_range( $url, $start, $end ) {
    $req = sprintf("%d-%d",$start, $end);
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_BINARYTRANSFER, 1);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
    curl_setopt($ch, CURLOPT_RANGE, $req);
    $results = curl_exec($ch);
    curl_close($ch);

    return $results;
}//curl_get_range

/*
 * sort_out_int - get int from zip directory
*/
function sort_out_int( $result, $start, $format, $len ) {
    $ident = mb_substr($result, $start, $len, '8bit');
    $dir = unpack($format, $ident);
    return (int)$dir[1];
}//sort_out_int

/*
 * sort_out_tile_display - use PHP image support
*/
function sort_out_tile_display( $file_data ) {
    $im = imagecreatefromstring($file_data);
    header('Content-Type: image/jpeg');
    imagejpeg($im);
    imagedestroy($im);
}//sort_out_tile_display

/*
 * sort_out_json_display - add url info to IIIF folder layout
*/
function sort_out_json_display( $file_data, $zip_path, $host, $script ) {
    header('Content-Type: application/json; charset=utf-8');
    $json_out = str_replace("\"/" . $zip_path,"\"" . $host . $script . "?path=/" . $zip_path,$file_data);
    echo $json_out;
}//sort_out_json_display

//extract path from url request
$url_components = parse_url($_SERVER['REQUEST_URI']);
parse_str($url_components['query'], $params);
$path_info = $params['path'];
$path_info = strtok($path_info, '?');

$is_img = TRUE;//assume image request by default

//no pdfs used in manifest (yet) but this is how a redirect would work
if(strpos($path_info, ".pdf") !== false) {
    header("Location: " . $WEB_STORAGE  . "/" . $path_info);
    exit();
}//if

$path_parts = explode("/",ltrim($path_info,"/"));
$path_len = $SCRIPT_PATH_LEN;

if(strpos($path_info, "manifest.json") !== false) $path_len -= 1;

$tile_folder = array_slice($path_parts, 0, $path_len);
$tile_asset = array_slice($path_parts,$path_len,strlen($path_info));

$zip_path = implode("/",$tile_folder);
$req_file = implode("/",$tile_asset);

if(strpos($req_file, "json") !== false) $is_img = FALSE;

$file_size = 0;
if(strpos($path_info, "manifest.json") !== false) {
    $url = $WEB_STORAGE . "/" . $zip_path . "/manifest.json";
    $file_data = file_get_contents($url);
    sort_out_json_display($file_data,$zip_path,$HOST,$SCRIPT);
    exit();
}//if 

$url = $WEB_STORAGE . "/" . $zip_path . "/tiles.zip";

$fn_name = str_replace("/","\/",$req_file);
$fn_name = str_replace(".","\.",$fn_name);
$fn_name = "tiles\/" . $fn_name;

if (strlen($ZIP_DIR_PATH) === 0) $file_size = curl_get_file_size($url);
	
if ($file_size > $END_OF_FILE_GAP || strlen($ZIP_DIR_PATH) > 0) {
    if (strlen($ZIP_DIR_PATH) === 0) { // no zip cache so get everything from web storage
        $result = curl_get_range($url,$file_size - $END_OF_FILE_GAP,$file_size);
        //look for end of directory record signature
        $match = preg_match('/' . $END_OF_DIR_SIGNATURE . '/', $result, $matches, PREG_OFFSET_CAPTURE);
        if ($match == 1) {
	    //we use the end of directory record to find the central directory record
            $pos = $matches[0][1] + 12;
            $ident = mb_substr($result, $pos, 10, '8bit');
            $dir = unpack("L2S", $ident);
            $size = (int)$dir['S1'];
            $offset = $dir['S2'];
            $result = curl_get_range($url,$offset,$offset + $size);
	}//if    
    } else { // use local cache
	$zip_dir_path = $ZIP_DIR_PATH . "/" . $zip_path . "/dir.bin";
        $file_size = filesize($zip_dir_path);
	if ($file_size > 0) {
            $fp = fopen($zip_dir_path, 'rb');
            $result = fread($fp, $file_size);
            fclose($fp);
	}//if    
    }//if

    //now should be working with the central directory record
    $match = preg_match('/' . $fn_name . '/', $result, $matches, PREG_OFFSET_CAPTURE);

    if ($match == 1) {
        $base_pos = $matches[0][1] - $CENTRAL_DIR_START;
        if ($base_pos >= 0) {
            //get needed values to calculate byte range for url request
	    $fn_len = sort_out_int($result,$base_pos + $FILE_NAME_LEN_POS,"S",2);
	    $ef_len = sort_out_int($result,$base_pos + $EXTRA_FIELD_LEN_POS,"S",2);
	    $fc_len = sort_out_int($result,$base_pos + $FIELD_COMMENT_LEN_POS,"S",2);
	    $comp_size = sort_out_int($result,$base_pos + $COMP_SIZE_POS,"I",4);
	    $rel_offset = sort_out_int($result,$base_pos + $REL_OFFSET_POS,"I",4);
	    $rel_offset = $rel_offset + $LOCAL_FILE_HEADER_LEN + $fn_len + $ef_len + $fc_len; 
	    //now get the requested file from zip archive
	    $file_data = curl_get_range($url,$rel_offset,$rel_offset + ($comp_size - 1));
            if (strlen($file_data) > 0) {
                if ($is_img) sort_out_tile_display($file_data);
                else sort_out_json_display($file_data,$zip_path,$HOST,$SCRIPT);
	    } //if
        } //if
    }//if
}//if

?>
