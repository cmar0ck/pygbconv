import sys
from PIL import Image
from collections import defaultdict
from math import floor, ceil, log

MAX_SUPPORTED_IMAGES = 256

def chunks(l, n):
    """ Yield successive n-sized chunks from l.
    """
    for i in xrange(0, len(l), n):
        yield l[i:i+n]

# Takes a size 64 tuple and returns 16 bytes in GB tile format
def convtile(tile_in):
	lines = chunks(tile_in, 8)
	tempstring=""
	
	for l in lines:
		lowerbyte=""
		upperbyte=""
		
		for b in l:
			lowerbyte += "1" if (b&1) else "0"
			upperbyte += "1" if (b&2) else "0"
	
		tempstring += chr(int(lowerbyte,2)) + chr(int(upperbyte,2)) 

	return tempstring

def convimg(name):
	print ("===Processing "+name)
	img = Image.open(name)
	
	w=img.size[0]
	h=img.size[1]
	
	if (w != 160 or h != 144):
		print ("Image must be exactly 160*144 big")
		exit()

	# Convert the image to RGB
	img = img.convert('RGB')	
	pixels = img.getdata()
	colors = []
	
	# Analyze the color content of the image
	for pxl in pixels:
		if not pxl in colors:
			colors.append(pxl)
		
		if len(colors)>4:
			break
	
	# Exit or warn if the number of colors isn't exactly 4
	if len(colors) > 4:
		print ("Image must contain no more than 4 unique colors. Do not use a file format that would destroy 4 color images such as JPEG. PNG, GIF and BMP (with any color depth) are ey-ok.")
		exit()
	elif len(colors) < 4:
		print ("Warning! Image has only " + str(len(colors)) + " unique colors (instead of exactly 4.) Color table will amended.")

	# Sort colors by brightness
	colors = sorted(colors, key=lambda c: c[0]+c[1]+c[2])

	# Fill up the color table if the image has less than colors
	if len(colors) == 2:
		colors = [colors[0],colors[1],colors[1],colors[1]]
	elif len(colors) == 3:
		colors = [colors[0],colors[1],colors[1],colors[2]]
	elif len(colors) == 1:
		print "Warning: This image only seems to have a single, solid color. How do you expect that to work, cap'n?"
		colors = [colors[0],colors[0],colors[0],colors[0]]

	colors_r = defaultdict(int)
	
	# Create reverse lookup table for color -> GB color index
	for i, color in enumerate(colors): 
		colors_r[color] = i

	# Convert RGB pixel an array consisting of values 0-3
	pixels_g = map(lambda x: colors_r[x], pixels)
	
	# Slice up the image in tile size chunks (end result, 8*8)
	# Slice up the pixel array into sections of rows of 8 pixel height
	pixels_g = chunks(pixels_g, w*8)

	# Slice up the rows of 8 pixels to tiles. Please help me make this more Pythonic if you can!
	tiles=[]

	# Iterate through each row of 8 pixel height
	for row in pixels_g:
		# Iterate through the number of tiles defined by the width
		for j in xrange(w/8):
			temp=[]
			# Iterate through 8 pieces of 8*1 pixel segments which together form a tile
			for k in xrange(8):
				temp+=row[j*8+k*w:j*8+k*w+8]
				
			tiles.append(temp)

	# Convert tiles into binary format used in Gameboy
	tiles = map(convtile, tiles)

	# Reverse lookup tile table to look for duplicate tiles that can be optimized away
	#tiles_r = defaultdict(int)
	# Tile map to be used for optimized tile sets
	tilemap = []
	tiles_o = []
	i = 0
	
	for t in tiles:
		# If tile doesn't exist in optimized tile set, add it
		if not t in tiles_o:
			tiles_o.append(t)
		
		# Add the tile to the map
		tilemap.append(tiles_o.index(t))
	
	# Convert to binary
	tilemap="".join(chr(x&0xff) for x in tilemap)
	
	if len(tiles_o)>256:
		print "Could not optimize image to below 256 tiles. Image stored as 360 tile image."
		tiles = "".join(x for x in tiles)
		return tiles, None
	else:
		print "Optimized image to", len(tiles_o), "tiles."
		tiles_o = "".join(x for x in tiles_o)
		return tiles_o, tilemap

def db(val):
	return chr(val&0xff)

def dw(val):
	return chr(val&0xff)+chr((val>>8)&0xff)

def dw_flip(val):
	return chr((val>>8)&0xff)+chr(val&0xff)

def gbheaderchecksum(r):
	acc=0
	for i in r[0x134:0x14d]:	
		acc += ~ord(i)
		acc &= 0xff
	
	return db(acc)

def gbglobalchecksum(r):
	acc=0
	for i in r:	
		acc += ord(i)
		acc &= 0xffff
	
	return dw_flip(acc)			# Global checksum has MSByte first!

def gbromfix(romdata):
	# Calculate header value for the ROM size
	romsize = int(ceil(log(len(romdata),32768)))
	
	# Restore target size that the ROM should be padded up to
	targetsize = 32768 << romsize

	# How many bytes are missing
	missingbytes = targetsize-len(romdata)

	# Append that many bytes
	romdata += chr(0xff)*missingbytes

	# Convert string to list in order to allow operations
	romdata = list(romdata)
	print len(romdata[0])
	# 
	romdata[0x148] = chr(romsize)			# ROM size header value

	romdata[0x14d] = gbheaderchecksum(romdata)	# Header checksum
	
	romdata[0x14e:0x150] = dw(0)			# Zero out global checksum
	romdata[0x14e:0x150] = gbglobalchecksum(romdata)

	romdata = "".join(romdata)
	
	return romdata

# Preamble IMG
# ROM table format, 4 bytes
# 1 byte  = Start bank (give 01 for data that starts in the home bank or 00 for last item)
# 2 bytes = Map start address
# 1 bytes = Number of tiles in the map-1, or 0 for sequential map data (for 360 tile mode)
def compilerom(gbin, gbout, images):
	gbtiles = map(convimg, images)
	f = open(gbin, "rb")
	baserom = f.read(16384)
	headerpart = "IMG"
	gfxpart = ""
	
	headersize = 4*len(images)+3+1
	
	for gt in gbtiles:
		accum = headersize + len(gfxpart)
		bank = (accum>>14)+1
		startaddr = accum % 16384 + 16384
		
		if gt[1] == None:
			numtiles = 0
			gfxpart += gt[0]
		else:
			numtiles = int(max(1,len(gt[0])/16-1))
			gfxpart += gt[1] + gt[0]
	
		headerpart += db(bank) + dw(startaddr) + db(numtiles)
		
	headerpart += chr(0)

	fout = open(gbout, "wb")
	fout.write(gbromfix(baserom+headerpart+gfxpart))
	fout.close()

def main():
	if len(sys.argv) < 3:
		# Too few: usage and exit.
		print "Usage: ./pygbconv.py output.gb image0.png image1.png ..."
		print "Outputs image slideshow ROM to (output.gb), for <= 256 images."
		print "Actual number of colors in each image must be four or less. Color depth can be anything that PIL can interpret."
		print "Do not use a file format that would destroy 4 color images, such as JPEG. PNG, GIF and BMP (with any color depth) are ey-ok."
		return 0
	elif 2 + MAX_SUPPORTED_IMAGES < len(sys.argv):
		# Too many: invalid
		print "Please keep it under {} images!" % (MAX_SUPPORTED_IMAGES)
		return 1

	compilerom("imagerom.gbbase", sys.argv[1], sys.argv[2:])
	return 0

if __name__ == "__main__":
	sys.exit(main())
