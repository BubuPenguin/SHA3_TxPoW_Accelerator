import java.util.Random;

public class start {

	static {
        System.loadLibrary("native");
    }
	
	public static void main(String[] zArgs) {
		System.out.println("JNI Demo..");
		
		//Create a new object
		start ss = new start();
		
		//Run the functions
		ss.sayHello();
		
		long sumint = ss.sumIntegers(1, 2);
		System.out.println("JNI sumIntegers returned : "+sumint);
		
		String welcome = ss.sayHelloToMe("paddy",false);
		System.out.println("JNI sayHelloToMe returned : "+welcome);
		
		//Create a random byte array
		Random rand = new Random();
		byte[] data = new byte[10];
		rand.nextBytes(data);
		
		//Run the function
		byte[] nonce = ss.hashHeader(data);
		
		System.out.println("JNI hashHeader input    : "+outputByteArray(data));
		System.out.println("JNI hashHeader returned : "+outputByteArray(nonce));
	}
	
	private static String outputByteArray(byte[] zData) {
		String ret = "";
		for(int i=0;i<zData.length;i++) {
			ret += Byte.toString(zData[i])+",";
		}
		return ret;
	}
	
	//JNI Methods..
	private native void sayHello();
    
    private native long sumIntegers(int first, int second);
    
    private native String sayHelloToMe(String name, boolean isFemale);
    
    private native byte[] hashHeader(byte[] headerbytes);
}
